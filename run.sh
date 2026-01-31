#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Starting SMS Keenetic Gateway..."

# Log configuration
HOST=$(bashio::config 'keenetic_host')
PORT=$(bashio::config 'port')
INTERFACE=$(bashio::config 'keenetic_modem_interface')

bashio::log.info "Keenetic Host: ${HOST}"
bashio::log.info "Modem Interface: ${INTERFACE}"
bashio::log.info "API Port: ${PORT}"

# Change to app directory
cd /app

# Start the application
bashio::log.info "Starting SMS Gateway application..."
python3 run.py
