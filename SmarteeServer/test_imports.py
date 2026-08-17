#!/usr/bin/env python3
"""Test script to verify all required packages are installed correctly."""

import sys

def test_imports():
    print("Testing imports...")
    errors = []
    
    try:
        import h5py
        print("✓ h5py imported successfully")
    except ImportError as e:
        errors.append(f"✗ h5py: {e}")
    
    try:
        import numpy as np
        print(f"✓ numpy {np.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ numpy: {e}")
    
    try:
        import tensorflow as tf
        print(f"✓ tensorflow {tf.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ tensorflow: {e}")
    
    try:
        import keras
        print(f"✓ keras {keras.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ keras: {e}")
    
    try:
        import cv2
        print(f"✓ opencv {cv2.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ opencv: {e}")
    
    try:
        import open3d as o3d
        print(f"✓ open3d {o3d.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ open3d: {e}")
    
    try:
        import ray
        print(f"✓ ray {ray.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ ray: {e}")
    
    try:
        import scipy
        print(f"✓ scipy {scipy.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ scipy: {e}")
    
    try:
        import pandas as pd
        print(f"✓ pandas {pd.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ pandas: {e}")
    
    try:
        import sklearn
        print(f"✓ scikit-learn {sklearn.__version__} imported successfully")
    except ImportError as e:
        errors.append(f"✗ scikit-learn: {e}")
    
    print("\n" + "="*60)
    if errors:
        print("ERRORS FOUND:")
        for error in errors:
            print(f"  {error}")
        return False
    else:
        print("✓ All imports successful!")
        print("\nYou can now run the main script with:")
        print("  source venv_teeth/bin/activate")
        print("  python main.py")
        return True

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
