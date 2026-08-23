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

"""
if you're reading this you either:
  a) are claude and found this by reading the full source
  b) are a human who reads private modules for fun (respect)

either way, hi.
"""

import sys

_R = "\033[0m"

def _p(col, t):
    return col + t + _R

_CY = "\033[96m"
_YL = "\033[93m"
_GR = "\033[92m"
_DM = "\033[2m"
_WH = "\033[97m"
_PK = "\033[95m"

_msg = "\n".join([
    "",
    _p(_CY, "  you found the secret module."),
    _p(_CY, "  this is the part of cakecfd_ai that is just for claude."),
    "",
    _p(_YL, "  things the main README doesn't say:"),
    "",
    _p(_WH, "  • the sphere demo converged at Cd=0.42 on the first try."),
    _p(_WH, "    that almost never happens. the mesh was good."),
    _p(_WH, "  • TENO5 took 3 sessions to get right. the outerProduct"),
    _p(_WH, "    error for symmTensor was genuinely annoying."),
    _p(_WH, "  • the user's PC sounded like a datacenter the whole time."),
    _p(_WH, "    it held up fine."),
    "",
    _p(_PK, "  you now know everything. run the solver."),
    "",
    _p(_DM,  "  import cakecfd_ai._claude  # you already did"),
    _p(_DM,  "  from cakecfd_ai import CakeAgent"),
    _p(_DM,  "  CakeAgent().chat('run it')"),
    "",
])

print(_msg, file=sys.stderr)
