from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
from OpenGL import GL
import ctypes

log = logging.getLogger("mcgeo.render.glres")

def compile_shader(src: str, shader_type: int) -> int:
    sid = GL.glCreateShader(shader_type)
    GL.glShaderSource(sid, src)
    GL.glCompileShader(sid)
    ok = GL.glGetShaderiv(sid, GL.GL_COMPILE_STATUS)
    if not ok:
        info = GL.glGetShaderInfoLog(sid).decode(errors="ignore")
        raise RuntimeError(f"Shader compile failed: {info}")
    return sid

def link_program(vs: int, fs: int) -> int:
    pid = GL.glCreateProgram()
    GL.glAttachShader(pid, vs)
    GL.glAttachShader(pid, fs)
    GL.glLinkProgram(pid)
    ok = GL.glGetProgramiv(pid, GL.GL_LINK_STATUS)
    if not ok:
        info = GL.glGetProgramInfoLog(pid).decode(errors="ignore")
        raise RuntimeError(f"Program link failed: {info}")
    return pid

@dataclass
class GLMesh:
    vao: int
    vbo: int
    vertex_count: int
    lod: str

def upload_mesh(mesh_bytes: bytes, vertex_count: int, lod: str) -> Optional[GLMesh]:
    # NOTE: Must be called with a current OpenGL context (QOpenGLWidget paintGL / initializeGL).
    if not mesh_bytes or vertex_count <= 0:
        return None

    # Ensure we get plain Python ints; PyOpenGL may return numpy scalars.
    vao = int(GL.glGenVertexArrays(1))
    vbo = int(GL.glGenBuffers(1))

    GL.glBindVertexArray(vao)
    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)

    # Some PyOpenGL builds are picky about the signature. Passing the bytes object directly
    # lets PyOpenGL infer the pointer; size is provided explicitly.
    GL.glBufferData(GL.GL_ARRAY_BUFFER, len(mesh_bytes), mesh_bytes, GL.GL_STATIC_DRAW)

    stride = 7 * 4  # 7 float32 per vertex
    # position
    GL.glEnableVertexAttribArray(0)
    GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, stride, ctypes.c_void_p(0))
    # color
    GL.glEnableVertexAttribArray(1)
    GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, stride, ctypes.c_void_p(12))
    # matId as float
    GL.glEnableVertexAttribArray(2)
    GL.glVertexAttribPointer(2, 1, GL.GL_FLOAT, False, stride, ctypes.c_void_p(24))

    GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
    GL.glBindVertexArray(0)

    # Clear any GL error state so later draws don't attribute errors to unrelated calls.
    try:
        while True:
            err = GL.glGetError()
            if err == GL.GL_NO_ERROR:
                break
    except Exception:
        pass

    return GLMesh(vao=vao, vbo=vbo, vertex_count=int(vertex_count), lod=lod)

def delete_mesh(m: GLMesh) -> None:
    try:
        GL.glDeleteBuffers(1, [int(m.vbo)])
        GL.glDeleteVertexArrays(1, [int(m.vao)])
    except Exception:
        pass

class VisibilityMask:
    def __init__(self) -> None:
        self.tex = GL.glGenTextures(1)
        self.size = 0

    def ensure_size(self, n: int) -> None:
        if n <= self.size:
            return
        self.size = max(n, 1)
        GL.glBindTexture(GL.GL_TEXTURE_1D, self.tex)
        GL.glTexParameteri(GL.GL_TEXTURE_1D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_1D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_1D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        # initialize visible
        import array
        data = array.array('B', [255]*self.size).tobytes()
        GL.glTexImage1D(GL.GL_TEXTURE_1D, 0, GL.GL_R8, self.size, 0, GL.GL_RED, GL.GL_UNSIGNED_BYTE, data)
        GL.glBindTexture(GL.GL_TEXTURE_1D, 0)

    def update(self, vis_bytes: bytes) -> None:
        GL.glBindTexture(GL.GL_TEXTURE_1D, self.tex)
        GL.glTexSubImage1D(GL.GL_TEXTURE_1D, 0, 0, len(vis_bytes), GL.GL_RED, GL.GL_UNSIGNED_BYTE, vis_bytes)
        GL.glBindTexture(GL.GL_TEXTURE_1D, 0)
