#!/bin/bash
set -e

# Add authorized key from environment
if [ -n "$SSH_AUTHORIZED_KEY" ]; then
    echo "$SSH_AUTHORIZED_KEY" > /home/testuser/.ssh/authorized_keys
    chown testuser:testuser /home/testuser/.ssh/authorized_keys
    chmod 600 /home/testuser/.ssh/authorized_keys
fi

# Start SSH daemon
/usr/sbin/sshd -D -e
