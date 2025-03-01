import asyncio
import logging
import time
import random
from typing import Dict
from telegram import Update
from telegram_bot.core.status import service_status
from telegram_bot.services.telegram_service import poll_all_bots, get_bot_tokens
from telegram_bot.handlers.message_handler import process_single_update

logger = logging.getLogger(__name__)

# Track last update IDs by bot token
last_update_ids: Dict[str, int] = {}

# Polling configuration
UPDATE_POLLING_INTERVAL = 5.0
UPDATE_TIMEOUT = 30

# Add missing variables for update lock and error tracking
update_lock = asyncio.Lock()
consecutive_errors = 0
last_error_time = 0

async def check_updates():
    """Check for updates from all configured Telegram bots."""
    global last_update_ids, consecutive_errors, last_error_time
    
    # Use a lock to ensure only one instance is requesting updates
    if update_lock.locked():
        logger.debug("Update check already in progress, skipping")
        return
        
    # Calculate backoff time based on consecutive errors
    backoff = min(300, 2 ** consecutive_errors) if consecutive_errors > 0 else 0
    current_time = time.time()
    if backoff > 0 and (current_time - last_error_time) < backoff:
        logger.info(f"Backing off for {backoff}s due to previous errors (waited {int(current_time - last_error_time)}s so far)")
        return
    
    # Try to acquire the lock, but don't block if we can't get it
    if not update_lock.locked():
        try:
            # Use asyncio.wait_for instead of asyncio.timeout
            async def acquire_and_process():
                global consecutive_errors, last_error_time, last_update_ids
                async with update_lock:
                    logger.debug("Acquired update lock, checking for updates")
                    try:
                        # Poll all bots for updates
                        all_updates, new_last_ids = await poll_all_bots(last_update_ids)
                        last_update_ids = new_last_ids
                        
                        if all_updates:
                            logger.info(f"Received {len(all_updates)} total updates from all bots")
                            
                            # Process each update in a separate task to avoid blocking
                            process_tasks = []
                            for update, token, name in all_updates:
                                # Update the status
                                service_status.update_last_update_id(update.update_id)
                                
                                # Log and process the update
                                logger.info(f"Processing update {update.update_id} from bot {name}")
                                task = asyncio.create_task(
                                    process_single_update(update, token)
                                )
                                process_tasks.append(task)
                            
                            # Wait for all tasks to complete with a reasonable timeout
                            if process_tasks:
                                done, pending = await asyncio.wait(
                                    process_tasks, 
                                    timeout=5,
                                    return_when=asyncio.ALL_COMPLETED
                                )
                                
                                # Log any pending tasks that didn't complete in time
                                if pending:
                                    logger.warning(f"{len(pending)} update processing tasks did not complete in time")
                        
                        # Reset error counter on success
                        if consecutive_errors > 0:
                            logger.info(f"Reset error counter after {consecutive_errors} consecutive errors")
                            consecutive_errors = 0
                            
                    except Exception as e:
                        # Track consecutive errors for backoff
                        consecutive_errors += 1
                        last_error_time = time.time()
                        logger.error(f"Error checking updates (attempt #{consecutive_errors}): {e}")
                        service_status.record_error(e)
                        
                        # Add jitter to avoid synchronization issues
                        jitter = random.uniform(0.5, 2)
                        await asyncio.sleep(jitter)
                    finally:
                        logger.debug("Released update lock")
                        
            # Use a shorter timeout to prevent blocking other operations for too long
            await asyncio.wait_for(acquire_and_process(), timeout=35)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for update lock, skipping this update check")
        except Exception as e:
            logger.error(f"Unexpected error in update check: {e}")
            service_status.record_error(e)

async def update_monitor():
    """Monitor and process new Telegram updates."""
    global last_update_ids
    reconnect_delay = 5
    
    # Wait briefly before starting to ensure all services are ready
    await asyncio.sleep(3)
    
    # Log startup status
    bot_tokens = get_bot_tokens()
    logger.info(f"Starting update monitor for {len(bot_tokens)} bots...")
    
    # Initialize update IDs if needed
    if not last_update_ids:
        logger.info("Initializing last update IDs...")
        for token, name in bot_tokens:
            last_update_ids[token] = 0
        logger.info(f"Initialized update IDs for {len(last_update_ids)} bots")
    
    # Main update loop
    failure_count = 0
    while True:
        try:
            # Get updates from all bots - one at a time with error handling
            updates_list, updated_ids = await poll_all_bots(last_update_ids)
            last_update_ids = updated_ids
            
            if updates_list:
                logger.info(f"Received {len(updates_list)} total updates from all bots")
                
                # Process each update one at a time
                for update, token, name in updates_list:
                    try:
                        service_status.update_last_update_id(update.update_id)
                        logger.info(f"Processing update {update.update_id} from bot {name}")
                        await process_single_update(update, token)
                    except Exception as e:
                        logger.error(f"Error processing update {update.update_id}: {e}")
            
            # Update activity timestamp
            service_status.update_activity()
            
            # Reset reconnect delay and failure count on successful cycle
            reconnect_delay = 5
            failure_count = 0
            
            # Sleep between update cycles (shorter when we received updates)
            sleep_time = 1 if updates_list else UPDATE_POLLING_INTERVAL
            await asyncio.sleep(sleep_time)
            
        except asyncio.CancelledError:
            logger.info("Update monitor task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in update monitor: {e}")
            service_status.record_error(e)
            
            # Increment failure count and slow down if we're having issues
            failure_count += 1
            if failure_count > 3:
                # If we're getting persistent errors, increase delay
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, 30)
            else:
                # For occasional errors, just add a small delay
                await asyncio.sleep(1)
