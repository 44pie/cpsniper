#!/bin/bash
# Мониторинг прогресса фильтрации

LOG_DIR="filtered_results"

echo "========================================"
echo "Progress Monitor - cPanelVulnFinder"
echo "========================================"
echo ""

while true; do
    total_processed=0
    total_found=0
    
    for log in ${LOG_DIR}/*.log 2>/dev/null; do
        if [ -f "$log" ]; then
            processed=$(grep -oE 'Normalized [0-9]+ targets' "$log" 2>/dev/null | tail -1 | grep -oE '[0-9]+' || echo 0)
            found=$(grep -oE 'Detected [0-9]+ cPanel/WHM targets' "$log" 2>/dev/null | tail -1 | grep -oE '[0-9]+' || echo 0)
            
            total_processed=$((total_processed + processed))
            total_found=$((total_found + found))
        fi
    done
    
    clear
    echo "========================================"
    echo "Progress Monitor"
    echo "========================================"
    echo ""
    echo "Processed: $total_processed"
    echo "Found cPanel: $total_found"
    echo ""
    echo "Press Ctrl+C to exit"
    echo "========================================"
    
    sleep 10
done
