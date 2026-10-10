import importlib
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: ./run-main.sh {assembly} [command] [options]")
        sys.exit(1)

    assembly_arg = sys.argv[1]

    # Normalize naming variations: e.g. phone-stand, phone_stand
    variations = [assembly_arg, assembly_arg.replace("-", "_"), assembly_arg.replace("_", "-")]

    assembly_dir = None
    assembly_pkg = None

    for var in variations:
        path = os.path.join("src", var)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "main.py")):
            assembly_dir = var
            assembly_pkg = f"src.{var}"
            break

    if not assembly_dir or not assembly_pkg:
        print(f"Error: Assembly '{assembly_arg}' not found under src/ as a package containing main.py.")
        print("Available assemblies:")
        if os.path.exists("src"):
            for entry in os.listdir("src"):
                if os.path.isdir(os.path.join("src", entry)) and os.path.exists(os.path.join("src", entry, "main.py")):
                    print(f" - {entry}")
        sys.exit(1)

    # Remove assembly name from sys.argv so click/CLI parser doesn't see it
    sys.argv.pop(1)

    try:
        module = importlib.import_module(f"{assembly_pkg}.main")
    except ModuleNotFoundError as e:
        print(f"Error loading assembly '{assembly_arg}': {e}")
        sys.exit(1)

    if not hasattr(module, "cli"):
        print(f"Error: Module '{assembly_pkg}.main' does not define a 'cli' Click group/command.")
        sys.exit(1)

    # Execute the Click CLI
    module.cli()


if __name__ == "__main__":
    main()
