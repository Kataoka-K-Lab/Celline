#!/usr/bin/env python3
"""
Celline Interactive Mode
Launches both the API server and frontend for interactive use
"""

import subprocess
import sys
import time
import threading
import webbrowser
import os
from pathlib import Path

def start_api_server():
    """Start the FastAPI server"""
    try:
        print("🚀 Starting Celline API server...")
        
        # Find the API startup script relative to this script's location
        current_script_dir = Path(__file__).parent.resolve()
        api_script = current_script_dir / "start_simple_api.py"
        
        print(f"🔧 Using API script: {api_script}")
        print(f"🔧 API script exists: {api_script.exists()}")
        
        # Start API server using simple script - show output for debugging
        proc = subprocess.Popen([
            sys.executable, str(api_script)
        ], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
        )
        
        # Read some initial output
        print("⏳ API server starting...")
        for i in range(5):
            if proc.poll() is not None:
                break
            time.sleep(1)
            print(f"   ... {i+1}/5 seconds")
        
        # Test if API is responding
        import requests
        try:
            print("🧪 Testing API connection...")
            response = requests.get("http://localhost:8000", timeout=5)
            if response.status_code == 200:
                print("✅ API server started successfully")
                print(f"📊 API response: {response.json()}")
                return proc
            else:
                print(f"❌ API server returned status {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"⚠️  API server test failed: {e}")
            # Check if process is still running
            if proc.poll() is None:
                print("⏳ API server process running, continuing anyway...")
                return proc
            else:
                # Read any error output
                stdout, stderr = proc.communicate()
                print(f"❌ API server process exited with code {proc.returncode}")
                if stdout:
                    print(f"Output: {stdout}")
                return None
        
    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        import traceback
        traceback.print_exc()
        return None

def start_frontend():
    """Start the Vue.js frontend"""
    try:
        # Find frontend directory relative to the celline source
        current_script_dir = Path(__file__).parent.resolve()
        celline_src_dir = current_script_dir.parent  # Go up to celline src directory
        frontend_path = celline_src_dir / "frontend"
        
        print(f"🔧 Looking for frontend at: {frontend_path}")
        
        if not frontend_path.exists():
            print("❌ Frontend directory not found at expected location")
            print(f"   Checked: {frontend_path}")
            return None
            
        print("🎨 Starting Celline frontend...")
        
        # Check if yarn is available
        try:
            subprocess.run(["yarn", "--version"], check=True, capture_output=True)
            use_yarn = True
            print("📦 Using Yarn package manager")
        except (subprocess.CalledProcessError, FileNotFoundError):
            use_yarn = False
            print("📦 Using npm package manager")
            
        if use_yarn:
            proc = subprocess.Popen([
                "yarn", "serve"
            ], cwd=frontend_path, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        else:
            proc = subprocess.Popen([
                "npm", "run", "serve"
            ], cwd=frontend_path, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        
        # Wait a moment for frontend to start
        print("⏳ Frontend starting... (this may take a moment)")
        time.sleep(8)
        
        # Check if frontend process is still running
        if proc.poll() is None:
            print("✅ Frontend started successfully")
            return proc
        else:
            print("❌ Frontend failed to start")
            return None
        
    except Exception as e:
        print(f"❌ Failed to start frontend: {e}")
        import traceback
        traceback.print_exc()
        return None

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import fastapi
        import uvicorn
        import requests
        print("✅ FastAPI dependencies found")
    except ImportError as e:
        print("❌ Required dependencies missing. Please install them:")
        print("   pip install fastapi uvicorn requests")
        print(f"   Missing: {e}")
        return False
        
    return True

def main():
    """Main function to start interactive mode"""
    print("🧬 Celline Interactive Mode")
    print("=" * 50)
    
    # Show current directory for debugging
    print(f"📁 Current directory: {os.getcwd()}")
    print(f"🐍 Python executable: {sys.executable}")
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Start API server
    print("\n🔧 Step 1: Starting API Server")
    api_proc = start_api_server()
    if not api_proc:
        print("❌ Failed to start API server")
        sys.exit(1)
    
    # Start frontend
    print("\n🔧 Step 2: Starting Frontend")
    frontend_proc = start_frontend()
    if not frontend_proc:
        print("❌ Failed to start frontend")
        if api_proc:
            print("🛑 Terminating API server...")
            api_proc.terminate()
        sys.exit(1)
    
    # Open browser
    print("\n🔧 Step 3: Opening Browser")
    print("🌐 Opening browser...")
    time.sleep(2)
    webbrowser.open("http://localhost:8080")
    
    print("\n" + "=" * 50)
    print("✅ Celline Interactive is running!")
    print("📊 API Server: http://localhost:8000")
    print("🎨 Frontend: http://localhost:8080")
    print("📖 API Docs: http://localhost:8000/docs")
    print("\n💡 If the browser doesn't open, manually visit:")
    print("   http://localhost:8080")
    print("\nPress Ctrl+C to stop all services...")
    print("=" * 50)
    
    try:
        # Keep running until interrupted
        while True:
            time.sleep(1)
            
            # Check if processes are still running
            if api_proc and api_proc.poll() is not None:
                print("❌ API server stopped unexpectedly")
                print(f"   Exit code: {api_proc.returncode}")
                break
                
            if frontend_proc and frontend_proc.poll() is not None:
                print("❌ Frontend stopped unexpectedly")
                print(f"   Exit code: {frontend_proc.returncode}")
                break
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping Celline Interactive...")
        
        # Terminate processes gracefully
        if api_proc:
            try:
                api_proc.terminate()
                api_proc.wait(timeout=5)
                print("✅ API server stopped")
            except subprocess.TimeoutExpired:
                api_proc.kill()
                print("⚠️  API server forcefully stopped")
            
        if frontend_proc:
            try:
                frontend_proc.terminate()
                frontend_proc.wait(timeout=5)
                print("✅ Frontend stopped")
            except subprocess.TimeoutExpired:
                frontend_proc.kill()
                print("⚠️  Frontend forcefully stopped")
        
        print("👋 Goodbye!")

if __name__ == "__main__":
    main()