#!/bin/bash

set -euo pipefail

# Trap to ensure cleanup on error
cleanup() {
    if [[ -n "${config_dir:-}" ]] && [[ -d "$config_dir" ]]; then
        rm -rf "$config_dir"
    fi
    if [[ -n "${bin_dir:-}" ]] && [[ -n "${exe_name:-}" ]] && [[ -f "$bin_dir/$exe_name" ]]; then
        rm -f "$bin_dir/$exe_name"
    fi
}
trap cleanup EXIT

test_executable() {
    local exe_path=$1
    local exe_name=$2
    local bin_dir=$3
    local config_dir=$4
    local is_zipapp=${5:-false}

    echo "  Testing $exe_name..."

    # Ensure config directory does not exist
    if [[ -d "$config_dir" ]]; then
        echo "ERROR: Config directory $config_dir already exists" >&2
        return 1
    fi

    # Create bin directory and prepare executable
    mkdir -p "$bin_dir"
    if [[ "$is_zipapp" == "true" ]]; then
        # Zipapp needs to be run with python
        cp "$exe_path" "$bin_dir/$exe_name"
        exe_cmd="python3 $bin_dir/$exe_name"
    else
        chmod +x "$exe_path" 2>/dev/null || true
        cp "$exe_path" "$bin_dir/$exe_name"
        exe_cmd="$bin_dir/$exe_name"
    fi

    # Test --help (basic sanity check)
    if ! $exe_cmd --help > /dev/null 2>&1; then
        echo "ERROR: --help failed" >&2
        return 1
    fi

    # Test --version
    local version_output
    version_output=$($exe_cmd --version)
    if [[ ! "$version_output" =~ [0-9]+\.[0-9]+\.[0-9]+ ]]; then
        echo "ERROR: Invalid version output: $version_output" >&2
        return 1
    fi
    echo "  Version: $version_output"

    # Test --init-config
    $exe_cmd --init-config

    # Verify config files exist
    if [[ ! -f "$config_dir/config.toml" ]]; then
        echo "ERROR: '$config_dir/config.toml' not created" >&2
        return 1
    fi

    # Cleanup
    rm -rf "$config_dir"
    rm -f "$bin_dir/$exe_name"
}

# Change to dist directory
if [[ ! -d "dist" ]]; then
    echo "ERROR: dist/ directory not found. Run from project root after building." >&2
    exit 1
fi

cd dist

# Detect OS and set variables
case "$(uname -s)" in
  Linux*)
    exe="pushback"
    bin_dir="$HOME/.local/bin"
    config_dir="$HOME/.config/pushback"
    
    archive=$(ls pushback-linux-x86_64-v*.tar.gz 2>/dev/null | head -n1)
    if [[ -z "$archive" ]]; then
        echo "ERROR: Linux archive not found" >&2
        exit 1
    fi
    tar xzf "$archive"
    ;;
    
  Darwin*)
    exe="pushback"
    bin_dir="$HOME/.local/bin"
    config_dir="$HOME/.config/pushback"
    
    archive=$(ls pushback-macos-universal2-v*.tar.gz 2>/dev/null | head -n1)
    if [[ -z "$archive" ]]; then
        echo "ERROR: macOS archive not found" >&2
        exit 1
    fi
    tar xzf "$archive"
    ;;
    
  MINGW*|MSYS*|CYGWIN*)
    exe="pushback.exe"
    bin_dir="$LOCALAPPDATA/Microsoft/WindowsApps"
    config_dir="$APPDATA/pushback"
    
    archive=$(ls pushback-windows-x86_64-v*.zip 2>/dev/null | head -n1)
    if [[ -z "$archive" ]]; then
        echo "ERROR: Windows archive not found" >&2
        exit 1
    fi
    powershell -Command "Expand-Archive -Path '$archive' -DestinationPath . -Force"
    ;;
    
  *)
    echo "ERROR: Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

echo "Testing standalone binary..."
test_executable "$exe" "$exe" "$bin_dir" "$config_dir" false
echo "✓ Standalone binary works"

echo ""
if [[ ! -f "pushback.pyz" ]]; then
    echo "pushback.pyz not found - skip testing zipapp" >&2
else
    echo "Testing zipapp..."
    test_executable "pushback.pyz" "pushback.pyz" "$bin_dir" "$config_dir" true
    echo "✓ Zipapp works"
fi

echo ""
echo "✓ All distribution artifacts tested successfully"
