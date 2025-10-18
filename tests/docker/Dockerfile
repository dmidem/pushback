FROM alpine:latest

# Install OpenSSH server and rsync
RUN apk add --no-cache \
    openssh-server \
    openssh-client \
    rsync \
    bash

# Create test user
RUN adduser -D -s /bin/bash testuser && \
    echo "testuser:testpass" | chpasswd

# Setup SSH
RUN ssh-keygen -A && \
    mkdir -p /home/testuser/.ssh && \
    chown -R testuser:testuser /home/testuser/.ssh && \
    chmod 700 /home/testuser/.ssh

# Configure SSHD
RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    sed -i 's/#PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Create backup directory
RUN mkdir -p /home/testuser/backups && \
    chown -R testuser:testuser /home/testuser/backups

# Startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
