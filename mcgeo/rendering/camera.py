from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Tuple

def _normalize(v):
    x,y,z = v
    n = math.sqrt(x*x+y*y+z*z) or 1.0
    return (x/n, y/n, z/n)

def _cross(a,b):
    ax,ay,az = a; bx,by,bz = b
    return (ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx)

def _dot(a,b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]

def mat4_identity():
    return [1,0,0,0,
            0,1,0,0,
            0,0,1,0,
            0,0,0,1]

def mat4_mul(a,b):
    # column-major 4x4
    out = [0]*16
    for c in range(4):
        for r in range(4):
            out[c*4+r] = (a[0*4+r]*b[c*4+0] +
                          a[1*4+r]*b[c*4+1] +
                          a[2*4+r]*b[c*4+2] +
                          a[3*4+r]*b[c*4+3])
    return out

def perspective(fov_y_deg: float, aspect: float, z_near: float, z_far: float):
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    nf = 1.0 / (z_near - z_far)
    return [
        f/aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (z_far+z_near)*nf, -1,
        0, 0, (2*z_far*z_near)*nf, 0,
    ]

def look_at(eye, target, up=(0.0,1.0,0.0)):
    f = _normalize((target[0]-eye[0], target[1]-eye[1], target[2]-eye[2]))
    s = _normalize(_cross(f, up))
    u = _cross(s, f)

    # column-major
    m = [
        s[0], u[0], -f[0], 0.0,
        s[1], u[1], -f[1], 0.0,
        s[2], u[2], -f[2], 0.0,
        0.0, 0.0,  0.0, 1.0,
    ]
    # translate
    t = [
        1,0,0,0,
        0,1,0,0,
        0,0,1,0,
        -eye[0], -eye[1], -eye[2], 1
    ]
    return mat4_mul(m, t)

@dataclass
class OrbitCamera:
    target: Tuple[float,float,float] = (0.0, 80.0, 0.0)
    yaw: float = 45.0
    pitch: float = 35.0
    distance: float = 120.0

    def clamp(self):
        self.pitch = max(-89.0, min(89.0, self.pitch))
        self.distance = max(4.0, min(4000.0, self.distance))

    def eye(self):
        self.clamp()
        ry = math.radians(self.yaw)
        rp = math.radians(self.pitch)
        cx = math.cos(rp) * math.cos(ry)
        cy = math.sin(rp)
        cz = math.cos(rp) * math.sin(ry)
        tx,ty,tz = self.target
        return (tx + cx*self.distance, ty + cy*self.distance, tz + cz*self.distance)

    def pan(self, dx: float, dy: float):
        # Pan in camera local plane
        e = self.eye()
        tx,ty,tz = self.target
        f = _normalize((tx-e[0], ty-e[1], tz-e[2]))
        right = _normalize(_cross(f, (0,1,0)))
        up = _normalize(_cross(right, f))
        scale = self.distance * 0.0015
        self.target = (tx - right[0]*dx*scale + up[0]*dy*scale,
                       ty - right[1]*dx*scale + up[1]*dy*scale,
                       tz - right[2]*dx*scale + up[2]*dy*scale)
