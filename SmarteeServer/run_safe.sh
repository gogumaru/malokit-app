#!/bin/bash

# Safe runner for 3D teeth reconstruction
# Handles segfaults by running in a loop with retries

PATIENT_ID="3"
MAX_RETRIES=3
RETRY_COUNT=0

echo "========================================================================"
echo "🦷 Safe Runner for 3D Teeth Reconstruction"
echo "========================================================================"
echo ""
echo "Patient ID: $PATIENT_ID"
echo "Max retries: $MAX_RETRIES"
echo ""

# Activate virtual environment
source venv_py39/bin/activate

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "----------------------------------------"
    echo "Attempt $(($RETRY_COUNT + 1)) of $MAX_RETRIES"
    echo "----------------------------------------"
    
    # Run with timeout (10 minutes)
    python main.py
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "✅ Success!"
        
        # Check if output files exist
        if [ -f "demo/mesh/$PATIENT_ID/Pred_Upper_Mesh_Tag=$PATIENT_ID.obj" ]; then
            echo ""
            echo "========================================================================"
            echo "✅ 3D RECONSTRUCTION COMPLETE!"
            echo "========================================================================"
            echo ""
            echo "📁 Results:"
            ls -lh demo/mesh/$PATIENT_ID/
            echo ""
            echo "🎉 DONE!"
            exit 0
        else
            echo "⚠️  Process exited successfully but files not found"
        fi
    elif [ $EXIT_CODE -eq 139 ]; then
        echo ""
        echo "❌ Segmentation fault detected (exit code 139)"
    else
        echo ""
        echo "❌ Process failed with exit code: $EXIT_CODE"
    fi
    
    RETRY_COUNT=$(($RETRY_COUNT + 1))
    
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo ""
        echo "⏳ Waiting 5 seconds before retry..."
        sleep 5
    fi
done

echo ""
echo "========================================================================"
echo "❌ Failed after $MAX_RETRIES attempts"
echo "========================================================================"
echo ""
echo "Suggestions:"
echo "1. Check log file: demo/_temp/Tag=$PATIENT_ID.log"
echo "2. Try reducing Ray CPUs in main.py (currently set to 2)"
echo "3. Restart your terminal and try again"
echo "4. Check system resources (Activity Monitor)"
echo ""

exit 1
