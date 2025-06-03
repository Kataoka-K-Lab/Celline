#!/usr/bin/env python3
"""
Simple API server startup script - no heavy dependencies
"""
import sys
import os
from pathlib import Path

# Determine the actual project root based on the caller's context
# This ensures it works whether called directly or from celline command
import inspect

def find_project_root():
    """Find the project root by looking for the celline package structure"""
    # Start from the current script's location
    current_path = Path(__file__).resolve()
    
    # Walk up the directory tree to find the project root
    for parent in [current_path.parent] + list(current_path.parents):
        # Look for the celline source structure
        if (parent / "src" / "celline").exists():
            return parent
        # Alternative: look for pyproject.toml
        if (parent / "pyproject.toml").exists():
            return parent
    
    # Fallback to relative path from script location
    return current_path.parent.parent.parent

project_root = find_project_root()
sys.path.insert(0, str(project_root / "src"))

print(f"🔧 Project root: {project_root}")
print(f"🔧 Working directory: {os.getcwd()}")

try:
    import uvicorn
    print("✅ uvicorn imported successfully")
    
    # Import the simple API module
    from celline.api.simple import app
    print("✅ Simple API module imported successfully")
    
    def main():
        print("🚀 Starting Celline Simple API server...")
        
        # Check if port 8000 is available
        import socket
        port = 8000
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                break
            except OSError:
                print(f"⚠️  Port {port} is in use, trying port {port + 1}...")
                port += 1
                if port > 8010:
                    print("❌ No available ports found")
                    return
        
        print(f"📡 Server will be available at: http://localhost:{port}")
        print(f"📖 API docs will be available at: http://localhost:{port}/docs")
        
        uvicorn.run(
            app, 
            host="127.0.0.1", 
            port=port,
            log_level="info",
            reload=False
        )
    
    if __name__ == "__main__":
        main()
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Please install missing dependencies:")
    print("pip install fastapi uvicorn")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error starting API server: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)