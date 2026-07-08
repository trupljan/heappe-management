import os
import shutil
import urllib.request
import subprocess
import hashlib
import json
import zipfile
import io

def check_and_generate_client(base_dir):
    # Files to look for in the repository root
    swagger_files = ["heappe_swagger.json", "swagger.json"]
    found_spec = None
    for f in swagger_files:
        path = os.path.join(base_dir, f)
        if os.path.exists(path):
            found_spec = path
            break

    local_dir = os.path.join(base_dir, "py4heappe", "heappe_v6")
    
    if not found_spec:
        # If no swagger json, clean up local directory if it was auto-generated
        marker_file = os.path.join(local_dir, ".auto_generated")
        if os.path.exists(marker_file):
            print("[heappe-generator] No Swagger spec found. Removing auto-generated local client to fallback to pip...")
            try:
                shutil.rmtree(local_dir)
                # If py4heappe folder is now empty, remove it as well
                parent_dir = os.path.dirname(local_dir)
                if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                    os.rmdir(parent_dir)
            except Exception as e:
                print(f"[heappe-generator] Error removing local client: {e}")
        return

    # If spec is found, check if we need to regenerate (hash compare)
    spec_hash = ""
    try:
        with open(found_spec, "rb") as sf:
            spec_hash = hashlib.md5(sf.read()).hexdigest()
    except Exception as e:
        print(f"[heappe-generator] Error hashing spec: {e}")

    hash_file = os.path.join(local_dir, ".spec_hash")
    need_generation = True
    if os.path.exists(local_dir) and os.path.exists(hash_file):
        try:
            with open(hash_file, "r") as hf:
                current_hash = hf.read().strip()
            if current_hash == spec_hash:
                need_generation = False
        except Exception:
            pass

    if not need_generation:
        return

    print(f"[heappe-generator] Found Swagger spec: {found_spec}. Generating local client...")
    
    # Temporary output directory for generated files
    temp_out = os.path.join(base_dir, "heappe_v6_temp")
    if os.path.exists(temp_out):
        try:
            shutil.rmtree(temp_out)
        except Exception:
            pass

    success = False

    # METHOD 1: Try generating via public Swagger Generator API (no Java/local tools required)
    try:
        print("[heappe-generator] Method 1: Attempting client generation via online Swagger Generator API...")
        with open(found_spec, "r", encoding="utf-8") as f:
            spec_data = json.load(f)
            
        payload = {
            "spec": spec_data,
            "options": {
                "packageName": "py4heappe.heappe_v6.core"
            }
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            "https://generator.swagger.io/api/gen/clients/python",
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        # Call API
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            zip_url = res_data['link']
            
        # Download ZIP package
        print(f"[heappe-generator] Downloading generated SDK from {zip_url}...")
        zip_response = urllib.request.urlopen(zip_url, timeout=30)
        zip_file = zipfile.ZipFile(io.BytesIO(zip_response.read()))
        
        # Locate the prefix inside ZIP file (usually 'python-client/')
        prefix = ""
        for name in zip_file.namelist():
            if name.endswith("py4heappe/heappe_v6/core/__init__.py"):
                prefix = name.split("py4heappe/heappe_v6/core/__init__.py")[0]
                break
                
        # Extract package contents into temp_out
        os.makedirs(temp_out, exist_ok=True)
        for member in zip_file.infolist():
            if member.filename.startswith(prefix):
                rel_path = member.filename[len(prefix):]
                if not rel_path:
                    continue
                target_path = os.path.join(temp_out, rel_path)
                if member.is_dir():
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as outfile:
                        outfile.write(zip_file.read(member.filename))
                        
        success = True
        print("[heappe-generator] Online generation succeeded!")
    except Exception as e:
        print(f"[heappe-generator] Online generation failed: {e}")

    # METHOD 2: Fallback to local swagger-codegen-cli JAR (requires Java)
    if not success:
        jar_path = os.path.join(base_dir, "swagger-codegen-cli-2.4.39.jar")
        if not os.path.exists(jar_path):
            url = "https://repo1.maven.org/maven2/io/swagger/swagger-codegen-cli/2.4.39/swagger-codegen-cli-2.4.39.jar"
            print(f"[heappe-generator] Downloading swagger-codegen-cli JAR from {url}...")
            try:
                urllib.request.urlretrieve(url, jar_path)
            except Exception as e:
                print(f"[heappe-generator] Failed to download generator JAR: {e}")
                jar_path = None

        if jar_path and os.path.exists(jar_path):
            cmd = [
                "java", "-jar", jar_path, "generate",
                "-i", found_spec,
                "-l", "python",
                "-o", temp_out,
                "-DpackageName=py4heappe.heappe_v6.core"
            ]
            print(f"[heappe-generator] Method 2: Running: {' '.join(cmd)}")
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    success = True
                else:
                    print(f"[heappe-generator] Codegen error:\n{res.stderr}")
            except Exception as e:
                print(f"[heappe-generator] Exception during codegen execution: {e}")

    # METHOD 3: Fallback to system openapi-generator-cli
    if not success:
        cmd = [
            "openapi-generator", "generate",
            "-i", found_spec,
            "-g", "python",
            "-o", temp_out,
            "--package-name", "py4heappe.heappe_v6.core"
        ]
        print(f"[heappe-generator] Method 3: Attempting fallback: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                success = True
            else:
                print(f"[heappe-generator] Openapi generator error:\n{res.stderr}")
        except Exception as e:
            print(f"[heappe-generator] Fallback exception: {e}")

    # Copy generated output into our permanent local directory
    if success:
        src_pkg = os.path.join(temp_out, "py4heappe", "heappe_v6")
        if not os.path.exists(src_pkg):
            # Fallback scan for core folder in output
            for root, dirs, files in os.walk(temp_out):
                if "core" in dirs and os.path.exists(os.path.join(root, "core", "__init__.py")):
                    src_pkg = root
                    break
        
        if os.path.exists(src_pkg):
            if os.path.exists(local_dir):
                try:
                    shutil.rmtree(local_dir)
                except Exception:
                    pass
            os.makedirs(os.path.dirname(local_dir), exist_ok=True)
            shutil.copytree(src_pkg, local_dir)
            
            # Write marker and hash files
            with open(os.path.join(local_dir, ".auto_generated"), "w") as mf:
                mf.write("auto-generated")
            with open(os.path.join(local_dir, ".spec_hash"), "w") as hf:
                hf.write(spec_hash)
            print("[heappe-generator] Local client generated successfully!")
        else:
            print(f"[heappe-generator] Error: Could not find generated package under {temp_out}")

    # Cleanup temp directory
    if os.path.exists(temp_out):
        try:
            shutil.rmtree(temp_out)
        except Exception:
            pass

if __name__ == "__main__":
    import sys
    base_dir = os.path.dirname(os.path.abspath(__file__))
    check_and_generate_client(base_dir)
