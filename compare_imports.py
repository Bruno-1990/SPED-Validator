import os
import re
from pathlib import Path

# Parse requirements
req_file = "requirements.txt"
packages_in_req = set()

with open(req_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.match(r'([a-zA-Z0-9_\-]+)', line)
        if match:
            pkg_name = match.group(1).lower()
            pkg_name = pkg_name.replace('-', '_')
            packages_in_req.add(pkg_name)

# Parse imports from code
root = Path(".")
import_pattern = r"^(?:from|import)\s+([a-zA-Z0-9_\.]+)"
imports = set()

for py_file in root.rglob("*.py"):
    if ".venv" in str(py_file) or "site-packages" in str(py_file) or "SPED/SPED" in str(py_file):
        continue
    try:
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith(('import ', 'from ')):
                match = re.match(import_pattern, line)
                if match:
                    module = match.group(1).split('.')[0]
                    imports.add(module.lower())
    except Exception:
        pass

# Stdlib
stdlib = {
    '__future__', 'abc', 'argparse', 'ast', 'asyncio', 'atexit', 'base64', 
    'collections', 'csv', 'dataclasses', 'datetime', 'decimal', 'difflib',
    'enum', 'functools', 'hashlib', 'hmac', 'http', 'io', 'inspect', 'json',
    'locale', 'logging', 'math', 'mmap', 'os', 'pathlib', 'pickle', 'platform',
    'pprint', 're', 'shutil', 'signal', 'socket', 'sqlite3', 'ssl', 'stat',
    'string', 'struct', 'subprocess', 'sys', 'tempfile', 'threading', 'time',
    'timeit', 'traceback', 'types', 'typing', 'unittest', 'urllib', 'warnings',
    'weakref', 'xml', 'zipfile', 'zlib', 'tkinter'
}

# Local
local = {'api', 'src', 'config', 'check_hardcoded_indices'}

# Third party in code (excluding empty strings)
third_party_in_code = {m for m in imports if m not in stdlib and m not in local and m.strip()}

# Special mappings for package names that differ from import names
package_import_map = {
    'pyyaml': 'yaml',
    'pillow': 'pil',
}

# Reverse mapping
import_package_map = {v: k for k, v in package_import_map.items()}

print("=" * 60)
print("MISSING FROM REQUIREMENTS (imported but not listed)")
print("=" * 60)

missing = []
for imp in sorted(third_party_in_code):
    pkg_name = import_package_map.get(imp, imp)
    # Check if it's in requirements (handle both original and normalized names)
    if pkg_name not in packages_in_req and imp not in packages_in_req:
        missing.append(imp)
        print(f"  {imp:30} -> likely {pkg_name}")

if not missing:
    print("  (None - all imports are in requirements)")

print("\n" + "=" * 60)
print("UNUSED IN REQUIREMENTS (listed but not imported)")
print("=" * 60)

unused = []
for pkg in sorted(packages_in_req):
    # Try direct match and reverse mapping
    found = False
    if pkg in third_party_in_code:
        found = True
    # Check if this package's import name is in the code
    import_name = import_package_map.get(pkg, pkg)
    if import_name in third_party_in_code:
        found = True
    # Special cases - dependencies used indirectly
    if pkg == 'pytest_cov' and 'pytest' in third_party_in_code:
        found = True  # pytest_cov is part of pytest ecosystem
    if pkg == 'python_multipart':
        found = True  # Used by fastapi implicitly for multipart/form-data
    if pkg == 'starlette':
        found = True  # Used by fastapi implicitly
    if pkg == 'uvicorn':
        found = True  # Server runner, not imported directly in code
    if pkg == 'httpx':
        found = True  # Used in tests via TestClient (fastapi.testclient uses it)
    if pkg == 'torch':
        found = True  # Used by sentence_transformers backend
    if pkg == 'docx':
        found = True  # May be implicit from pdfplumber or other tools
    
    if not found:
        unused.append(pkg)
        print(f"  {pkg:30}")

if not unused:
    print("  (None - all requirements appear to be used)")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Third-party packages in code:       {len(third_party_in_code)}")
print(f"Packages in requirements.txt:        {len(packages_in_req)}")
print(f"Missing from requirements:          {len(missing)}")
print(f"Unused in requirements:             {len(unused)}")
print(f"\nThird-party imports found:")
for imp in sorted(third_party_in_code):
    print(f"  {imp}")
