# Elasticsearch Setup for LangGraph Studio on Linux

This document explains how to configure Elasticsearch to work with LangGraph Studio on Linux systems, specifically addressing the common Docker networking issues.

## Problem

When running LangGraph Studio on Linux, you may encounter connection errors like:

```
elastic_transport.ConnectionError: Connection error caused by: ConnectionError(Connection error caused by: NameResolutionError(<urllib3.connection.HTTPConnection object>: Failed to resolve 'host.docker.internal' ([Errno -2] Name or service not known)))
```

This happens because:
1. `host.docker.internal` doesn't work reliably on Linux systems
2. LangGraph Studio runs in Docker containers that need to communicate with Elasticsearch
3. Default Docker networking configurations can prevent proper communication

## Solution

### Step 1: Stop and Remove Existing Elasticsearch Container

If you have an existing Elasticsearch container, stop and remove it:

```bash
docker stop elasticsearch
docker rm elasticsearch
```

### Step 2: Find the Docker Network Gateway IP

Find the gateway IP for the LangGraph Studio network:

```bash
docker network inspect krrs_default | grep -A 5 -B 5 Gateway
```

This will show you the gateway IP (typically something like `172.18.0.1`).

### Step 3: Start Elasticsearch with Proper Configuration

Start Elasticsearch with the correct network configuration:

```bash
docker run -p 9200:9200 -d --name elasticsearch \
  -e ELASTIC_PASSWORD="your_password_here" \
  -e "discovery.type=single-node" \
  -e "xpack.security.http.ssl.enabled=false" \
  -e "xpack.license.self_generated.type=trial" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

**Important Notes:**
- Use `-p 9200:9200` (not `-p 127.0.0.1:9200:9200`) to bind to all interfaces
- Replace `your_password_here` with your actual password
- The container will be accessible from both localhost and the Docker gateway IP

### Step 4: Update Environment Configuration

Update your `.env` file with the gateway IP address:

```properties
## Elastic local:
ELASTICSEARCH_URL=http://172.18.0.1:9200
ELASTICSEARCH_HOST=172.18.0.1
ELASTICSEARCH_PORT=9200
ELASTICSEARCH_USER=elastic
ELASTICSEARCH_PASSWORD=your_password_here
```

**Replace `172.18.0.1` with the actual gateway IP from Step 2.**

### Step 5: Restart LangGraph Studio

Restart the LangGraph API container to pick up the new environment variables:

```bash
docker restart krrs-langgraph-api-1
```

Wait for it to become healthy:

```bash
docker ps | grep krrs-langgraph-api
```

You should see `(healthy)` in the status.

## Verification

### Test Local Connection

Test that Elasticsearch is accessible from your host:

```bash
curl -u elastic:"your_password_here" http://localhost:9200
```

### Test Gateway IP Connection

Test that Elasticsearch is accessible via the gateway IP:

```bash
curl -u elastic:"your_password_here" http://172.18.0.1:9200
```

Both should return a JSON response with Elasticsearch cluster information.

## Alternative Approaches

If the above doesn't work, you can try these alternatives:

### Option 1: Use Host Network Mode

Run Elasticsearch with host networking:

```bash
docker run --network host -d --name elasticsearch \
  -e ELASTIC_PASSWORD="your_password_here" \
  -e "discovery.type=single-node" \
  -e "xpack.security.http.ssl.enabled=false" \
  -e "xpack.license.self_generated.type=trial" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

Then use `localhost:9200` in your `.env` file.

### Option 2: Add to Same Network

Add Elasticsearch to the same network as LangGraph Studio:

```bash
docker run -p 9200:9200 -d --name elasticsearch --network krrs_default \
  -e ELASTIC_PASSWORD="your_password_here" \
  -e "discovery.type=single-node" \
  -e "xpack.security.http.ssl.enabled=false" \
  -e "xpack.license.self_generated.type=trial" \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.1
```

Then use `elasticsearch:9200` as the URL in your `.env` file.

## Troubleshooting

### Check Container Status

```bash
docker ps | grep elasticsearch
docker logs elasticsearch
```

### Check Network Configuration

```bash
docker network ls
docker network inspect krrs_default
```

### Check LangGraph Studio Logs

```bash
docker logs krrs-langgraph-api-1
```

### Verify Environment Variables

Check that LangGraph Studio picked up the new environment:

```bash
docker exec krrs-langgraph-api-1 env | grep ELASTICSEARCH
```

## Common Issues

1. **Container exits immediately**: Check the logs for authentication or configuration errors
2. **Still getting connection refused**: Verify the port binding and firewall settings
3. **Host resolution errors**: Make sure you're using the correct IP address, not hostname
4. **Permission denied**: Check that the Elasticsearch password matches in both the container and `.env` file

## Security Notes

- This setup is for development only
- For production, enable SSL and use proper authentication
- Consider using Docker Compose for more complex setups
- Never commit passwords to version control
