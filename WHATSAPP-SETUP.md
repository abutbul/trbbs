# WhatsApp Bot Setup Guide

## Local Development Testing

1. Start the Docker Compose application:
   ```
   docker-compose up -d
   ```

2. Access the test interface to simulate WhatsApp messages:
   ```
   http://localhost:8082/test-ui
   ```

3. You can also send test messages using curl:
   ```
   curl -X POST http://localhost:8082/test-webhook \
     -H "Content-Type: application/json" \
     -d '{"from": "123456789", "message": "help"}'
   ```

4. Check the logs to see if your message is being processed:
   ```
   docker-compose logs -f whatsapp-pubsub
   ```

## Production Deployment

For WhatsApp to send real messages to your webhook, you need a public HTTPS URL. Options:

### Option 1: Deploy to a server with a domain name
1. Get a domain name and point it to your server
2. Set up HTTPS with Let's Encrypt
3. Configure your firewall to allow port 443 (HTTPS)
4. Update the Docker Compose file to use a production-ready reverse proxy

### Option 2: Use a tunneling service (for testing only)
1. Use a service like ngrok, Cloudflare Tunnel, or Webhook.site
2. Point the tunnel to your local Docker service (port 8082)
3. Update your WhatsApp Business API configuration with the tunnel URL

## WhatsApp Business API Configuration

1. Go to Facebook Developers Portal
2. Set up a WhatsApp Business account
3. Configure webhooks to point to your public URL + `/webhook` path
4. Use the same verify token as set in your environment variables
5. Subscribe to the message events

## Troubleshooting

- **Not receiving messages**: Check the logs with `docker-compose logs -f whatsapp-pubsub`
- **Webhook verification fails**: Ensure your WEBHOOK_VERIFY_TOKEN matches the one in Meta Dashboard
- **Authentication errors**: Check if your WhatsApp token is valid and not expired
