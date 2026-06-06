## [0.0.3] - 2026-06-06

### 🐛 Bug Fixes

- *(ci)* Force QT_QPA_PLATFORM=offscreen during the AppImage build
## [0.0.2] - 2026-06-06

### 🐛 Bug Fixes

- *(ci)* Install the [gui] extra so PyInstaller bundles Qt

### ⚙️ Miscellaneous Tasks

- Generate the changelog with git-cliff, synced to the tag
- *(release)* V0.0.2
## [0.0.1] - 2026-06-06

### 🚀 Features

- Implemented main page of the GUI
- Added settings tab
- Added AppImage generation
- Added windows .exe builder
- Config file is now loaded from workspace
- Added git cliff for changelog
- Added test scripts
- Dynamic list for connected boards (gui)
- Added make instructions for Windows (MSYS2/Chocolatey)
- Added cross-platform compilation (MinGW) for pyfers
- Added compression style for the configuration file (channel params now are default + exceptions)

### 🐛 Bug Fixes

- Ferslib build (linux)
- Connection error w/o board (linux)
- Corrected discriminator tab
- Fixed install for pyferslib
- PyInstaller spec missing due to .gitignore file
- Link pyferslib against static ferslib on Windows

### 💼 Other

- Ignored build directories (whatever starts with build*)

### 🎨 Styling

- Added icons
- "config file loaded from workspace" look improved
- Added HQ logos
- Fixed arrows for selectors
- Style for config "chip"
- Adjusted CAEN logo

### ⚙️ Miscellaneous Tasks

- Track the mingw-w64 cross-build toolchain file
- Add bump-my-version config for project-wide versioning
- *(release)* V0.0.1
