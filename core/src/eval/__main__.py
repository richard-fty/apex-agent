"""Allow running as: python -m harness.runner"""
from eval.runner import main
import asyncio

asyncio.run(main())
