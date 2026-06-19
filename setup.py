from setuptools import setup


setup(
    name="delux-agent",
    version="0.1.0",
    description="Shell-first AI agent for fish with local memory, docs, and self-documenting skills.",
    packages=["delux_agent"],
    entry_points={"console_scripts": ["delux=delux_agent.cli:main"]},
    python_requires=">=3.11",
)
