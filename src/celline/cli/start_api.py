#!/usr/bin/env python3
"""
Direct API server startup script
"""
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

print(f"🔧 Project root: {project_root}")
print(f"🔧 Python path: {sys.path}")

try:
    import uvicorn
    print("✅ uvicorn imported successfully")
    
    # Import minimal dependencies first
    import toml
    print("✅ toml imported successfully")
    
    # Now import the API module
    from celline.api.main import app
    print("✅ API module imported successfully")
    
    if __name__ == "__main__":
        print("🚀 Starting Celline API server directly...")
        print("📡 Server will be available at: http://localhost:8000")
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=8000,
            log_level="info",
            reload=False  # Disable reload to avoid issues
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