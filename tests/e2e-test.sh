#!/usr/bin/env bash
set -Eeuo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$SCRIPT_DIR/docker"
DOCKERFILE="$DOCKER_DIR/Dockerfile"

# Use system temp directory for test artifacts
TEST_TEMP="${TMPDIR:-/tmp}/pushback-e2e-$$"
TEST_HOME="$TEST_TEMP/home"
TEST_SSH_DIR="$TEST_HOME/.ssh"
TEST_CONFIG_DIR="$TEST_HOME/.config/pushback"
TEST_PROJECT="$TEST_TEMP/test-project"

# Docker configuration
IMAGE_NAME="pushback-test-sshd"
CONTAINER_NAME="pushback-test-sshd-$$"
SSH_PORT=2222

# Label all test containers so we can nuke leftovers reliably
LABEL_KEY="com.pushback.test"
LABEL_VAL="e2e"
# Common prefix for pre-clearing by name (regex anchor ^ enforces prefix match)
NAME_PREFIX="pushback-test-sshd-"

# Cleanup function
cleanup() {
    local exit_code=$?
    echo -e "${YELLOW}Cleaning up...${NC}"

    # Stop/remove *this* container if it exists
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

    # Remove any leftover test containers from previous runs (by label)
    docker ps -aq -f "label=$LABEL_KEY=$LABEL_VAL" | xargs -r docker rm -f

    # Extra safety: remove by name prefix (in case older runs lacked labels)
    docker ps -aq --filter "name=^${NAME_PREFIX}" | xargs -r docker rm -f

    # Remove temp directory
    [ -d "$TEST_TEMP" ] && rm -rf "$TEST_TEMP"

    # Optional: prune stopped containers as a last resort (keeps running ones)
    docker container prune -f >/dev/null 2>&1 || true
    # Keep your image prune if you like:
    docker image prune -f >/dev/null 2>&1 || true

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✓ Cleanup complete${NC}"
    else
        echo -e "${RED}✗ Tests failed (exit code: $exit_code)${NC}"
    fi
    exit $exit_code
}

trap cleanup EXIT INT TERM

# Helper functions
log_step() {
    echo -e "${GREEN}▶${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_step "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Please install Docker."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon not running. Please start Docker."
        exit 1
    fi

    if [ ! -f "$DOCKERFILE" ]; then
        log_error "Dockerfile not found at: $DOCKERFILE"
        exit 1
    fi

    log_success "Prerequisites OK"
}

# Setup test environment
setup_test_env() {
    log_step "Setting up test environment..."

    # Create test directories
    mkdir -p "$TEST_SSH_DIR" "$TEST_CONFIG_DIR" "$TEST_PROJECT"
    chmod 700 "$TEST_SSH_DIR"

    # Generate SSH key (non-interactive)
    log_step "Generating SSH test key..."
    ssh-keygen -t ed25519 -f "$TEST_SSH_DIR/id_ed25519" -N "" -C "pushback-test" >/dev/null
    chmod 600 "$TEST_SSH_DIR/id_ed25519"
    chmod 644 "$TEST_SSH_DIR/id_ed25519.pub"

    # Create test project with various files
    log_step "Creating test project..."

    cat > "$TEST_PROJECT/README.md" << 'EOF'
# Test Project

This is a test project for pushback.
EOF

    mkdir -p "$TEST_PROJECT/src" "$TEST_PROJECT/.git"
    echo "print('hello')" > "$TEST_PROJECT/src/main.py"
    echo "*.pyc" > "$TEST_PROJECT/.gitignore"
    touch "$TEST_PROJECT/src/test.pyc"

    # Create .backupignore
    cat > "$TEST_PROJECT/.backupignore" << 'EOF'
.git/
*.pyc
EOF

    log_success "Test environment ready at: $TEST_TEMP"
}

# Start SSH server and configure SSH client
start_ssh_server() {
    log_step "Building Docker image..."

    # Clean up any existing containers with same name
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    # Also remove any leftovers from prior runs (prefix + label)
    docker ps -aq --filter "name=^${NAME_PREFIX}" | xargs -r docker rm -f
    docker ps -aq -f "label=$LABEL_KEY=$LABEL_VAL" | xargs -r docker rm -f

    # Build image (reuse if exists and unchanged)
    if ! docker build -t "$IMAGE_NAME" "$DOCKER_DIR"; then
        log_error "Failed to build Docker image"
        exit 1
    fi

    log_step "Starting SSH server container..."

    # Run container with test SSH key
    if ! docker run -d --rm \
        --label "$LABEL_KEY=$LABEL_VAL" \
        --name "$CONTAINER_NAME" \
        -p "$SSH_PORT:22" \
        -e "SSH_AUTHORIZED_KEY=$(cat "$TEST_SSH_DIR/id_ed25519.pub")" \
        "$IMAGE_NAME"; then
        log_error "Failed to start container"
        exit 1
    fi

    # Wait for SSH to be ready
    log_step "Waiting for SSH server to be ready..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if ssh-keyscan -p "$SSH_PORT" localhost 2>/dev/null | grep -q "ssh"; then
            break
        fi
        retries=$((retries - 1))
        sleep 1
    done

    if [ $retries -eq 0 ]; then
        log_error "SSH server failed to start"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi

    # Add host key for port 2222 to known_hosts
    log_step "Adding SSH host key..."
    ssh-keyscan -p "$SSH_PORT" localhost >> "$TEST_SSH_DIR/known_hosts" 2>/dev/null
    chmod 644 "$TEST_SSH_DIR/known_hosts"

    # Test SSH connection with correct port
    log_step "Testing SSH connection..."
    if ! ssh -i "$TEST_SSH_DIR/id_ed25519" \
           -o StrictHostKeyChecking=no \
           -o UserKnownHostsFile="$TEST_SSH_DIR/known_hosts" \
           -p "$SSH_PORT" \
           testuser@localhost "echo 'SSH test successful'" >/dev/null 2>&1; then
        log_error "SSH connection test failed"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi
    log_success "SSH connection verified"
}

# Create pushback config
create_config() {
    log_step "Creating pushback configuration..."

    cat > "$TEST_CONFIG_DIR/config.toml" << EOF
[options]
delete_remote = false
snapshot_mode = "none"
include_backupignore = true
include_gitignore = true
autodetect_profiles = true
check_dependencies = true

[[server]]
name = "test"
user = "testuser"
host = "localhost"
port = $SSH_PORT
base = "~/backups"
default = true
EOF

    # Copy default profiles
    if [ -f "$PROJECT_ROOT/src/pushback/_embedded/profiles.toml" ]; then
        cp "$PROJECT_ROOT/src/pushback/_embedded/profiles.toml" \
           "$TEST_CONFIG_DIR/profiles.toml"
    fi

    log_success "Configuration created"
}

# Run pushback tests
run_pushback_tests() {
    log_step "Running pushback tests..."

    # Completely isolate environment
    export HOME="$TEST_HOME"
    export XDG_CONFIG_HOME="$TEST_HOME/.config"
    export SSH_AUTH_SOCK=""  # Don't use system SSH agent
    unset SSH_AGENT_PID 2>/dev/null || true

    # Create SSH config with ABSOLUTE paths
    cat > "$TEST_SSH_DIR/config" << EOF
Host localhost
    HostName localhost
    Port $SSH_PORT
    User testuser
    IdentityFile $TEST_SSH_DIR/id_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile $TEST_SSH_DIR/known_hosts
EOF

    chmod 600 "$TEST_SSH_DIR/config"

    SHIM_DIR="$TEST_TEMP/bin"
    mkdir -p "$SHIM_DIR"
    cat > "$SHIM_DIR/ssh" <<EOF
#!/usr/bin/env bash
exec /usr/bin/ssh -F "$TEST_SSH_DIR/config" "\$@"
EOF
    chmod +x "$SHIM_DIR/ssh"

    # Force SSH and rsync to use our config file
    export GIT_SSH_COMMAND="ssh -F $TEST_SSH_DIR/config"
    export RSYNC_RSH="ssh -F $TEST_SSH_DIR/config"

    # Wrapper function to run pushback with isolated environment
    run_pushback() {
        env -i \
            HOME="$TEST_HOME" \
            XDG_CONFIG_HOME="$TEST_HOME/.config" \
            PATH="$SHIM_DIR:$PATH" \
            PYTHONPATH="${PYTHONPATH:-}" \
            GIT_SSH_COMMAND="ssh -F $TEST_SSH_DIR/config" \
            RSYNC_RSH="ssh -F $TEST_SSH_DIR/config" \
            python -m pushback "$@"
    }

    # Test 1: Basic sync
    log_step "Test 1: Basic sync"
    if ! run_pushback --verbose "$TEST_PROJECT"; then
        log_error "Basic sync failed"

        # Debug with explicit config
        echo "=== SSH Config ===" >&2
        cat "$TEST_SSH_DIR/config" >&2
        echo "=== SSH Test with -F flag ===" >&2
        ssh -F "$TEST_SSH_DIR/config" localhost "echo 'Direct SSH test works'" 2>&1 >&2 || true
        echo "=== Rsync test ===" >&2
        rsync -e "ssh -F $TEST_SSH_DIR/config" -avz "$TEST_PROJECT/" localhost:~/test-rsync/ 2>&1 >&2 || true

        return 1
    fi
    log_success "Basic sync OK"

    # Test 2: Verify files on remote
    log_step "Test 2: Verify remote files"
    local remote_files
    remote_files=$(ssh -F "$TEST_SSH_DIR/config" localhost \
                       "find ~/backups -type f -name '*.md' -o -name '*.py'" 2>/dev/null || true)

    if ! echo "$remote_files" | grep -q "README.md"; then
        log_error "README.md not found on remote"
        echo "Remote files found:" >&2
        echo "$remote_files" >&2
        return 1
    fi

    if ! echo "$remote_files" | grep -q "main.py"; then
        log_error "main.py not found on remote"
        return 1
    fi

    if echo "$remote_files" | grep -q "test.pyc"; then
        log_error "test.pyc should be ignored but was synced"
        return 1
    fi
    log_success "Remote files verified"

    # Test 3: List backups
    log_step "Test 3: List remote backups"
    if ! run_pushback --list-remote; then
        log_error "List backups failed"
        return 1
    fi
    log_success "List backups OK"

    # Test 4: Dry run
    log_step "Test 4: Dry run"
    if ! run_pushback --dry-run "$TEST_PROJECT"; then
        log_error "Dry run failed"
        return 1
    fi
    log_success "Dry run OK"

    # Test 5: Snapshot mode
    log_step "Test 5: Daily snapshot"
    if ! run_pushback --snapshot-mode daily "$TEST_PROJECT"; then
        log_error "Snapshot mode failed"
        return 1
    fi
    log_success "Snapshot mode OK"

    # Test 6: Delete mode
    log_step "Test 6: Delete mode"
    echo "new file" > "$TEST_PROJECT/new.txt"
    if ! run_pushback --delete "$TEST_PROJECT"; then
        log_error "Delete mode failed"
        return 1
    fi
    log_success "Delete mode OK"

    # Test 7: Size filters
    log_step "Test 7: Size filters"
    dd if=/dev/zero of="$TEST_PROJECT/large.bin" bs=1M count=2 2>/dev/null
    if ! run_pushback --max-size 1M --dry-run "$TEST_PROJECT"; then
        log_error "Size filter failed"
        return 1
    fi
    log_success "Size filter OK"

    log_success "All tests passed!"
    return 0
}

# Main execution
main() {
    echo -e "${GREEN}Pushback E2E Test Suite${NC}"
    echo "========================================"

    check_prerequisites
    setup_test_env
    start_ssh_server
    create_config

    if run_pushback_tests; then
        echo ""
        echo -e "${GREEN}════════════════════════════════════════${NC}"
        echo -e "${GREEN}  All E2E tests passed successfully!  ${NC}"
        echo -e "${GREEN}════════════════════════════════════════${NC}"
        exit 0
    else
        echo ""
        echo -e "${RED}════════════════════════════════════════${NC}"
        echo -e "${RED}  E2E tests failed                     ${NC}"
        echo -e "${RED}════════════════════════════════════════${NC}"
        exit 1
    fi
}

main "$@"
