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
                parent_dir = os.path.dirname(local_dir)
                init_file = os.path.join(parent_dir, "__init__.py")
                if os.path.exists(init_file):
                    os.remove(init_file)
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

    # Clean up old v2 jar if present
    old_jar = os.path.join(base_dir, "swagger-codegen-cli-2.4.39.jar")
    if os.path.exists(old_jar):
        try:
            os.remove(old_jar)
        except Exception:
            pass

    # METHOD 1: Try generating using swagger-codegen-cli v3 with custom templates (requires Java)
    jar_path = os.path.join(base_dir, "swagger-codegen-cli-3.0.71.jar")
    if not os.path.exists(jar_path):
        url = "https://repo1.maven.org/maven2/io/swagger/codegen/v3/swagger-codegen-cli/3.0.71/swagger-codegen-cli-3.0.71.jar"
        print(f"[heappe-generator] Downloading swagger-codegen-cli v3 JAR from {url}...")
        try:
            urllib.request.urlretrieve(url, jar_path)
        except Exception as e:
            print(f"[heappe-generator] Failed to download generator JAR: {e}")
            jar_path = None

    if jar_path and os.path.exists(jar_path):
        templates_path = os.path.join(base_dir, "codegen_templates", "Templates", "python")
        if not os.path.exists(templates_path):
            templates_path = os.path.join(base_dir, "codegen_templates", "python")
        
        config_path = os.path.join(base_dir, "codegen_config.json")
        
        cmd = [
            "java", "-jar", jar_path, "generate",
            "-i", found_spec,
            "-l", "python",
            "-o", temp_out
        ]
        if os.path.exists(templates_path):
            cmd += ["-t", templates_path]
        if os.path.exists(config_path):
            cmd += ["-c", config_path]
        else:
            cmd += ["-DpackageName=py4heappe.heappe_v6.core"]
            
        print(f"[heappe-generator] Method 1: Running: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                success = True
                print("[heappe-generator] Local JAR generation succeeded!")
            else:
                print(f"[heappe-generator] Codegen error:\n{res.stderr}")
        except Exception as e:
            print(f"[heappe-generator] Exception during codegen execution: {e}")

    # METHOD 2: Try generating via public Swagger Generator v3 API as fallback
    if not success:
        try:
            print("[heappe-generator] Method 2: Attempting client generation via online Swagger Generator V3 API...")
            with open(found_spec, "r", encoding="utf-8") as f:
                spec_data = json.load(f)
                
            payload = {
                "lang": "python",
                "spec": spec_data,
                "type": "CLIENT",
                "codegenVersion": "V3",
                "options": {
                    "additionalProperties": {
                        "packageName": "py4heappe.heappe_v6.core",
                        "projectName": "Py4HEAppE"
                    }
                }
            }
            
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                "https://generator3.swagger.io/api/generate",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                zip_data = response.read()
                
            print(f"[heappe-generator] Extracting received ZIP package...")
            zip_file = zipfile.ZipFile(io.BytesIO(zip_data))
            
            prefix = ""
            for name in zip_file.namelist():
                if name.endswith("py4heappe/heappe_v6/core/__init__.py"):
                    prefix = name.split("py4heappe/heappe_v6/core/__init__.py")[0]
                    break
                    
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
            print("[heappe-generator] Online generation V3 succeeded!")
        except Exception as e:
            print(f"[heappe-generator] Online generation V3 failed: {e}")

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
            
            # Create local package marker if not present
            init_file = os.path.join(os.path.dirname(local_dir), "__init__.py")
            if not os.path.exists(init_file):
                with open(init_file, "w") as f:
                    f.write("# Local py4heappe package marker\n")
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
