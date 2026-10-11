# PyInstaller entry point for the windowed app (examnet.gui uses relative imports,
# so it can't be the build script itself).
from examnet.gui import main

if __name__ == "__main__":
    main()
