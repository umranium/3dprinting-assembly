"""Type stubs for the parts of pyclipper the printability checks use.

pyclipper is a thin wrapper around a C++ extension module, so it ships no types of its own and
every call into it would otherwise be an unchecked attribute on an opaque module. Only what
tests.printability actually calls is declared here; a path is a closed outline as a list of
integer [x, y] pairs, and a list of paths is an outline set with its holes.
"""

from typing import Sequence

_Path = list[list[int]]
_Paths = list[_Path]

CT_INTERSECTION: int
CT_UNION: int
CT_DIFFERENCE: int
CT_XOR: int

PT_SUBJECT: int
PT_CLIP: int

PFT_EVENODD: int
PFT_NONZERO: int

JT_ROUND: int
JT_SQUARE: int
JT_MITER: int

ET_CLOSEDPOLYGON: int
ET_CLOSEDLINE: int

class PyPolyNode:
    Contour: _Path
    Childs: list[PyPolyNode]
    IsHole: bool

class Pyclipper:
    def AddPath(self, path: Sequence[Sequence[int]], poly_type: int, closed: bool) -> None: ...
    def AddPaths(self, paths: Sequence[Sequence[Sequence[int]]], poly_type: int, closed: bool) -> None: ...
    def Execute(self, clip_type: int, subj_fill_type: int = ..., clip_fill_type: int = ...) -> _Paths: ...
    def Execute2(self, clip_type: int, subj_fill_type: int = ..., clip_fill_type: int = ...) -> PyPolyNode: ...

class PyclipperOffset:
    ArcTolerance: float
    MiterLimit: float
    def AddPath(self, path: Sequence[Sequence[int]], join_type: int, end_type: int) -> None: ...
    def AddPaths(self, paths: Sequence[Sequence[Sequence[int]]], join_type: int, end_type: int) -> None: ...
    def Execute(self, delta: float) -> _Paths: ...

def Area(poly: Sequence[Sequence[int]]) -> float: ...
def MinkowskiSum(pattern: Sequence[Sequence[int]], path: Sequence[Sequence[int]], path_is_closed: bool) -> _Paths: ...
def ReversePath(path: Sequence[Sequence[int]]) -> _Path: ...
def Orientation(poly: Sequence[Sequence[int]]) -> bool: ...
