#!/usr/bin/env python3
"""
Standalone API server for Celline Interactive
This version avoids heavy dependencies by directly importing only the API module
"""
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import uvicorn
    
    # Import the API directly
    from celline.api.main import app
    
    if __name__ == "__main__":
        print("🚀 Starting Celline API server (standalone)...")
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=8000,
            log_level="info"
        )
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Please install missing dependencies:")
    print("pip install fastapi uvicorn toml")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error starting API server: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)