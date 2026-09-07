# Copyright (C) 2026 CakeCFD Contributors
#
# This file is part of CakeCFD.
#
# CakeCFD is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# CakeCFD is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# CakeCFD. If not, see <https://www.gnu.org/licenses/>.

"""Basic smoke tests for tool implementations (no real OF needed)."""
import json
import pytest
from pathlib import Path
from cakecfd_ai.tool_impl import read_forces, read_residuals, write_case_param


def test_read_residuals_missing(tmp_path):
    result = read_residuals(str(tmp_path))
    assert "error" in result


def test_read_forces_missing(tmp_path):
    result = read_forces(str(tmp_path))
    assert "error" in result


def test_write_case_param_missing(tmp_path):
    result = write_case_param(str(tmp_path), "system/controlDict", "endTime", "500")
    assert result.get("success") is False or "error" in result