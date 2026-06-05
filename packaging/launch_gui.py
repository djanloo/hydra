"""PyInstaller entry point for the HydraFERS desktop GUI.

A thin launcher so PyInstaller analyses a real script (not ``-m``); it keeps the
package import context intact by importing the GUI ``main`` and delegating to it.
"""

import sys

from hydrafers.gui.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
