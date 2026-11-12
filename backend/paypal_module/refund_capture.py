"""
ProofBridge refund CLI entrypoint wrapper.
"""
import os
import sys

# Add paypal_module to path if needed
pkg_dir = os.path.join(os.path.dirname(__file__), "paypal_module")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from paypal_module.refund_capture import main

if __name__ == "__main__":
    main()
