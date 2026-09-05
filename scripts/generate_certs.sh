#!/bin/bash
# Generate mTLS certificates for local development and testing

set -e

CERTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"
mkdir -p "$CERTS_DIR"

echo "Generating mTLS certificates in $CERTS_DIR..."

# 1. Generate CA key and certificate
openssl genrsa -out "$CERTS_DIR/ca.key" 4096
openssl req -new -x509 -days 3650 -key "$CERTS_DIR/ca.key" -out "$CERTS_DIR/ca.crt" -subj "/C=US/ST=State/L=City/O=AIWorkloadOrch/OU=CA/CN=AIWorkloadCA"

# 2. Generate Server (Control Plane) key and certificate
openssl genrsa -out "$CERTS_DIR/server.key" 2048
openssl req -new -key "$CERTS_DIR/server.key" -out "$CERTS_DIR/server.csr" -subj "/C=US/ST=State/L=City/O=AIWorkloadOrch/OU=ControlPlane/CN=localhost"
openssl x509 -req -days 365 -in "$CERTS_DIR/server.csr" -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" -set_serial 01 -out "$CERTS_DIR/server.crt"

# 3. Generate Client (Node Agent) key and certificate
openssl genrsa -out "$CERTS_DIR/client.key" 2048
openssl req -new -key "$CERTS_DIR/client.key" -out "$CERTS_DIR/client.csr" -subj "/C=US/ST=State/L=City/O=AIWorkloadOrch/OU=NodeAgent/CN=node-agent"
openssl x509 -req -days 365 -in "$CERTS_DIR/client.csr" -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" -set_serial 02 -out "$CERTS_DIR/client.crt"

# Set restrictive permissions
chmod 600 "$CERTS_DIR"/*.key

echo "Done! Certificates generated in $CERTS_DIR."
