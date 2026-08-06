# SearXNG image for Ask Kriton's web-search grounding, ready for cloud deploy
# (e.g. Render). Locally, docker-compose mounts ./searxng into /etc/searxng;
# in the cloud there is no local folder to mount, so we bake our settings.yml
# (which enables the JSON format the backend calls) straight into the image.
FROM searxng/searxng:latest

# Copy our custom settings (JSON format enabled + secret key) to the path
# SearXNG reads its configuration from.
COPY settings.yml /etc/searxng/settings.yml
