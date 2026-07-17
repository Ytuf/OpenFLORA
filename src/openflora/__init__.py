"""OpenFLORA: open-solver MILP floorplanner for FPGA partial reconfiguration.

A from-the-papers, permissively-licensed reimplementation of the FLORA
floorplanning approach (Seyoum/Biondi/Buttazzo, CODES+ISSS 2019) on the
MIT-licensed HiGHS solver, with a measured configuration-frame objective.
See the README for provenance and credits.
"""
from . import bitparse, cli, device, emit, frames, milp  # noqa: F401

__version__ = "0.1.0"
