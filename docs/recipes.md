# Recipes

Practical, copy‑paste friendly examples.

## Simple backup of the current folder
```bash
pushback .
```

## Daily project backup (no questions asked)
```bash
pushback --force-all ~/projects/myapp
```

## Development backup with dry-run preview
```bash
pushback --dry-run --verbose .
```

## Selective backup excluding build artifacts
```bash
cd ~/projects/myapp
cat >> .backupignore << 'EOF'
build/
node_modules/
*.log
!important.log
EOF
pushback .
```

## Multiple projects batch backup
```bash
for dir in ~/projects/*/; do
  echo "Backing up: $(basename "$dir")"
  pushback --force-all "$dir"
done
```

## Weekly snapshots with large-file review
```bash
pushback --snapshot-mode weekly --verbose ~/projects/webapp
```

## Monthly archive with large-file auto-ignore
```bash
pushback --snapshot-mode monthly --force-backupignore ~/important-project
```

## Hourly CI artifacts
```bash
pushback --snapshot-mode hourly --force-all ~/ci/artifacts
```

## Backup to a specific server
```bash
pushback --server backup ~/important-docs
```

## Backup to multiple servers
```bash
pushback --server primary,offsite --force-all ~/critical-project
```

## List existing backups (optionally filter by name prefix)
```bash
pushback --list-remote
pushback --list-remote myproject
```

## Resolve collisions automatically
```bash
# If a same-named project exists in a different path/snapshot
pushback --force-collision-new /path/to/project      # create new copy
pushback --force-collision-update /path/to/project   # update existing one
```

## Show rsync stats + throttle bandwidth
```bash
pushback --stats --rsync-extra "--bwlimit=1000" .
```

## Custom snapshots every 6 hours
```bash
pushback --snapshot-mode custom --snapshot-custom-hours 6 ~/projects/data
```
