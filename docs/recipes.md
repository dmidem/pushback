# Usage Recipes

Copy-paste friendly examples for common scenarios.

---

## Basic Operations

### Simple backup
```bash
pushback .
```

### Preview changes
```bash
pushback --dry-run .
```

### Detailed preview
```bash
pushback --dry-run --verbose .
```

### Backup with statistics
```bash
pushback --stats ~/projects/myapp
```

---

## Snapshots

### Daily snapshots
```bash
pushback --snapshot-mode daily ~/projects/webapp
```

**Result:**
```
~/pushback/webapp_2025-01-15/
~/pushback/webapp_2025-01-16/
~/pushback/webapp_2025-01-17/
```

### Weekly snapshots (Monday-Sunday)
```bash
pushback --snapshot-mode weekly ~/documents
```

**Result:**
```
~/pushback/documents_2025W02/
~/pushback/documents_2025W03/
```

### Hourly snapshots
```bash
pushback --snapshot-mode hourly ~/logs
```

**Result:**
```
~/pushback/logs_2025-01-15H10/
~/pushback/logs_2025-01-15H11/
~/pushback/logs_2025-01-15H12/
```

### Custom 6-hour intervals
```bash
pushback --snapshot-mode custom --snapshot-custom-hours 6 ~/data
```

**Result:**
```
~/pushback/data_I12340/
~/pushback/data_I12341/
~/pushback/data_I12342/
```

---

## Multiple Servers

### Backup to specific server
```bash
pushback --server offsite ~/critical-data
```

### Backup to multiple servers simultaneously
```bash
pushback --server primary,offsite ~/important-project
```

### List configured servers
```bash
pushback --list-servers
```

**Output:**
```
Configured servers:
  primary: user@backup1.example.com:22 -> ~/backups (default)
  offsite: user@backup2.example.com:2222 -> ~/archive
```

---

## Filtering

### Create project-specific ignore file
```bash
cd ~/projects/myapp

cat > .backupignore << 'EOF'
# Exclude build artifacts
build/
dist/
*.log

# But keep these
!important.log
!build/README.txt
EOF

pushback .
```

### Skip large files
```bash
pushback --max-size 500M ~/videos
```

### Skip tiny files
```bash
pushback --min-size 1K ~/logs
```

### Use .gitignore instead of .backupignore
```bash
pushback -g --no-include-backupignore .
```

### Combine all filter sources
```bash
pushback -b -g --autodetect-profiles .
```

### Disable profile auto-detection (manual only)
```bash
pushback --no-autodetect-profiles .
```

---

## Remote Management

### List all remote backups
```bash
pushback --list-remote
```

**Output:**
```
Remote backups on primary (user@backup1.example.com):
  webapp_2025-01-15
  webapp_2025-01-16
  docs_a1b2c3d4
  project_2025W03
```

### List backups for specific project
```bash
pushback --list-remote myproject
```

**Output:**
```
Remote backups on primary (user@backup1.example.com):
  myproject_2025-01-15
  myproject_2025-01-16
  myproject_2025-01-17
```

### Enable remote deletion (sync mode)
```bash
# Always preview first!
pushback --dry-run --delete .

# Review output, then:
pushback --delete .
```

⚠️ **Important:** rsync only deletes **files**, not directories. Empty directories are removed automatically, but directories containing excluded files will remain.

---

## Automation

### Non-interactive backup (for scripts/cron)
```bash
pushback --force-all ~/projects/myapp
```

### Batch backup multiple projects
```bash
#!/bin/bash
for dir in ~/projects/*/; do
  echo "Backing up: $(basename "$dir")"
  pushback --force-all --snapshot-mode daily "$dir"
done
```

### Daily cron job (2 AM)
```bash
# Add to: crontab -e
0 2 * * * /home/user/.local/bin/pushback --force-all ~/important-project
```

### Hourly cron job (CI artifacts)
```bash
# Add to: crontab -e
0 * * * * /home/user/.local/bin/pushback --force-all --snapshot-mode hourly ~/ci/artifacts
```

---

## Development Workflows

### Preview changes before backup
```bash
pushback --dry-run --verbose .
```

### Backup before major refactor
```bash
# Create hourly snapshot before risky changes
pushback --snapshot-mode hourly --force-all ~/projects/webapp

# Make changes
git checkout -b major-refactor
# ... work ...
```

### Archive completed projects
```bash
pushback --snapshot-mode yearly ~/archive/old-project
```

### Quick backup during development
```bash
# Add to .git/hooks/pre-push (make executable)
#!/bin/bash
pushback --force-all .
```

---

## Advanced Scenarios

### Bandwidth limiting
```bash
pushback --rsync-extra "--bwlimit=1000" .
```

### Preserve exact timestamps and permissions
```bash
pushback --rsync-extra "--times --perms" .
```

### Exclude specific file types temporarily
```bash
# Create temporary filter
echo "*.mp4" > /tmp/extra-ignore
pushback --rsync-extra "--filter='merge /tmp/extra-ignore'" .
```
> **Warning:** Providing `--rsync-extra "-e …"` replaces the SSH command used by pushback and disables the built-in multiplexing options. Only use it when you intend to override the SSH configuration entirely.

### Backup to custom SSH port (per-command)
```bash
# Better: configure in config.toml
# [[server]]
# port = 2222

pushback --rsync-extra "-e 'ssh -p 2222'" --server custom .
```

### Verify backup integrity
```bash
# Dry-run with checksum verification
pushback --dry-run --rsync-extra "--checksum" .
```
> Checksums force rsync to re-read every file locally and remotely; use only for troubleshooting or infrequent integrity checks.

---

## Collision Handling

When multiple directories match your project:

### Auto-create new directory
```bash
pushback --force-collision-new /path/to/project
```

### Auto-update most recent directory
```bash
pushback --force-collision-update /path/to/project
```

### Interactive choice (default)
```bash
pushback /path/to/project
```

**Output:**
```
Multiple matching backups found:
  1. myproject_a1b2c3d4 (modified: 2025-01-14)
  2. myproject_e5f6g7h8 (modified: 2025-01-15)

Choose: [1/2/new] (or Ctrl-C to cancel):
```

---

## Filter Configuration Examples

### Python project with custom rules
```toml
# ~/.config/pushback/profiles.toml
[profile.my_python]
detect.all_of = ["pyproject.toml", "src/"]
ignore = [
    "__pycache__/",
    ".venv/",
    "*.pyc",
    "dist/",
    "build/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "htmlcov/",
    ".coverage",
]
```

### Node.js project
```bash
# Project .backupignore
node_modules/
dist/
build/
.next/
.nuxt/
.cache/
*.log
.env.local
```

### Mixed project (Python + Node)
```toml
# Profiles automatically combine when both detected
# profiles.toml already has [profile.python] and [profile.node]
```

---

## Troubleshooting

### View active filters
```bash
pushback --dry-run --verbose . | grep -A 20 "Active profiles"
```

### Test specific filter configuration
```bash
# Disable all filters
pushback --no-include-backupignore --no-include-gitignore --no-autodetect-profiles --dry-run .

# Only profiles
pushback --no-include-backupignore --no-include-gitignore --dry-run .

# Only .backupignore
pushback --no-autodetect-profiles --dry-run .
```

### Debug SSH connection
```bash
# Verbose SSH output
pushback --rsync-extra "-e 'ssh -vvv'" .
```

### Check remote directory structure
```bash
ssh user@host "ls -lh ~/pushback/"
```

---

## Best Practices

### Regular backups
```bash
# Set up daily cron
0 2 * * * pushback --force-all --snapshot-mode daily ~/projects/important
```

### Test before deployment
```bash
# Always dry-run first
pushback --dry-run --verbose .

# Then execute
pushback .
```

### Version control integration
```bash
# .git/hooks/post-commit
#!/bin/bash
pushback --force-all --snapshot-mode hourly .
```

### Monitor backup size
```bash
# Check remote disk usage
ssh user@host "du -sh ~/pushback/*" | sort -h
```
