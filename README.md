# Telegram Rule Based Bot System

## Project Overview

This project implements a flexible Telegram bot system with rule-based messaging capabilities, designed with a microservices architecture for scalability and maintainability.

### Primary Purpose

The system provides a framework for creating and operating multiple Telegram bots with custom rule-based response patterns. It allows for easy configuration and management of multiple bots through a unified codebase.

## Key Features

- **Rule-based responses**: Each bot can have multiple regex-based rules that trigger different responses
- **Multiple bot support**: Can run several Telegram bots simultaneously with one codebase
- **Context-aware rules**: Different rules for direct messages vs group chats
- **Script execution**: Can execute shell scripts and return outputs as responses
- **Command routing**: Supports @botname syntax for targeting specific bots

## Getting Started

### Prerequisites

- Docker and Docker Compose installed
- Telegram Bot API token(s)

### Setup and Run

1. Clone the repository:
   ```
   git clone https://github.com/abutbul/trbbs
   cd trbbs
   ```

2. Copy the example configuration file:
   ```
   cp bot_config.json.example bot_config.json
   ```

3. Edit `bot_config.json` and add your Telegram bot tokens

4. Start the services using Docker Compose:
   ```
   docker compose up -d
   ```

5. Check service status:
   ```
   docker compose ps
   ```

## System Architecture

The system is composed of three main components:

1. **telegram_bot**: Handles Telegram API interaction
   - Receives messages from Telegram
   - Sends responses back to users
   - Maintains bot connections and health monitoring

2. **bot_logic**: Processes messages and generates responses
   - Matches messages against rule patterns
   - Executes appropriate response actions
   - Maintains message processing state

3. **Redis**: Acts as message broker between components
   - Messages flow: Telegram → Redis → bot_logic → Redis → Telegram

The system uses Docker containers orchestrated with docker-compose.yml:
- **telegram-pubsub**: Container for the Telegram API interface
- **bot-logic**: Container for message processing logic
- **redis**: Message broker between services

## Key Design Decisions

- **Separation of concerns**: Telegram communication is isolated from business logic
- **Asynchronous processing**: All components use async/await for better performance
- **Error resilience**: Comprehensive error handling with backoff strategies
- **Health monitoring**: All services expose health status for monitoring
- **Configuration-driven**: Bot behavior defined in bot_config.json without code changes

## Work Done

### System Architecture
- Implemented microservices architecture with Docker containers
- Set up Redis as message broker between components
- Created Telegram API integration
- Implemented rule-based message processing
- Established health monitoring for services

### Core Components
- **telegram_bot**: Handles Telegram API interaction
- **bot_logic**: Processes messages and generates responses
- **Redis**: Acts as message broker between components

### Documentation
- Created Memory Bank (March 1, 2025)
- Documented system architecture and components
- Established documentation structure

## Next Steps

### Short-term Tasks
- Review and optimize message processing pipeline
- Enhance error handling and resilience
- Improve logging and monitoring
- Add more comprehensive test coverage

### Medium-term Goals
- Implement additional response types beyond regex matching
- Add support for media messages (images, audio, etc.)
- Create admin dashboard for bot management
- Implement analytics for message patterns and usage

### Long-term Vision
- Scale system to handle higher message volumes
- Add machine learning capabilities for smarter responses
- Implement user context tracking for personalized interactions
- Create a visual rule builder for non-technical users