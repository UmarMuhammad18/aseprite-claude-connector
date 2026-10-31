"""Isometric drawing tools — a differentiator.

No other Aseprite MCP ships isometric primitives; the popular servers are all
flat-canvas. These draw true 2:1 isometric forms with automatic top/left/right
face shading (light from top-left), clean strokes, and a top-edge highlight —
built for isometric game art. Each is one undo step on the live editor.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run
from .look import previewable

# Shared iso helpers, prepended to each tool body (kept out of the core prelude).
_ISO = """
local function pp(img,x,y,c) x=math.floor(x+0.5);y=math.floor(y+0.5); if x>=0 and y>=0 and x<img.width and y<img.height then img:drawPixel(x,y,c) end end
local function pline(img,x0,y0,x1,y1,c) x0=math.floor(x0+0.5);y0=math.floor(y0+0.5);x1=math.floor(x1+0.5);y1=math.floor(y1+0.5)
  local dx=math.abs(x1-x0);local dy=-math.abs(y1-y0);local sx=x0<x1 and 1 or -1;local sy=y0<y1 and 1 or -1;local e=dx+dy
  while true do pp(img,x0,y0,c); if x0==x1 and y0==y1 then break end; local e2=2*e; if e2>=dy then e=e+dy;x0=x0+sx end; if e2<=dx then e=e+dx;y0=y0+sy end end end
local function polyfill(img,pts,c) local miny,maxy=1e9,-1e9
  for _,p in ipairs(pts) do if p[2]<miny then miny=p[2] end; if p[2]>maxy then maxy=p[2] end end
  miny=math.max(0,math.floor(miny)); maxy=math.min(img.height-1,math.ceil(maxy))
  for y=miny,maxy do local xs={} for i=1,#pts do local a=pts[i];local b=pts[(i%#pts)+1]
    if (a[2]<=y and b[2]>y) or (b[2]<=y and a[2]>y) then xs[#xs+1]=a[1]+(y-a[2])/(b[2]-a[2])*(b[1]-a[1]) end end
    if #xs>=2 then table.sort(xs); for x=math.max(0,math.floor(xs[1]+0.5)),math.min(img.width-1,math.floor(xs[#xs]+0.5)) do img:drawPixel(x,y,c) end end end end
local function faces(r,g,b) local pc=app.pixelColor
  local function s(f) return pc.rgba(math.min(255,math.floor(r*f)),math.min(255,math.floor(g*f)),math.min(255,math.floor(b*f)),255) end
  return {top=pc.rgba(r,g,b,255), left=s(0.70), right=s(0.48), stroke=s(0.20), hi=s(1.30)} end
"""

_BOX = (
    _ISO
    + """
return editCel(function(img, s)
  local hw=HW; local half=hw/2
  local gL={CX-hw,CY}; local gR={CX+hw,CY}; local gF={CX,CY+half}; local gB={CX,CY-half}
  local tL={gL[1],gL[2]-HT}; local tR={gR[1],gR[2]-HT}; local tF={gF[1],gF[2]-HT}; local tB={gB[1],gB[2]-HT}
  local p=faces(R,G,B)
  polyfill(img,{tL,tB,tR,tF},p.top); polyfill(img,{gL,gF,tF,tL},p.left); polyfill(img,{gF,gR,tR,tF},p.right)
  local S=p.stroke
  pline(img,tL[1],tL[2],tB[1],tB[2],S);pline(img,tB[1],tB[2],tR[1],tR[2],S);pline(img,tR[1],tR[2],tF[1],tF[2],S);pline(img,tF[1],tF[2],tL[1],tL[2],S)
  pline(img,gL[1],gL[2],tL[1],tL[2],S);pline(img,gF[1],gF[2],tF[1],tF[2],S);pline(img,gR[1],gR[2],tR[1],tR[2],S)
  pline(img,gL[1],gL[2],gF[1],gF[2],S);pline(img,gF[1],gF[2],gR[1],gR[2],S)
  pline(img,tL[1],tL[2],tF[1],tF[2],p.hi);pline(img,tF[1],tF[2],tR[1],tR[2],p.hi)
  return J({ top={{tL[1],tL[2]},{tB[1],tB[2]},{tR[1],tR[2]},{tF[1],tF[2]}},
    face_se={{gF[1],gF[2]},{gR[1],gR[2]},{tR[1],tR[2]},{tF[1],tF[2]}},
    face_sw={{gL[1],gL[2]},{gF[1],gF[2]},{tF[1],tF[2]},{tL[1],tL[2]}} })
end)
"""
)

_CYL = (
    _ISO
    + """
return editCel(function(img, s)
  local cx,topY,r,h=CX,TY,RAD,HT; local ry=math.floor(r/2); local p=faces(R,G,B)
  for y=0,h do for x=-r,r do pp(img,cx+x,topY+y, (x<-r*0.35) and p.hi or (x<r*0.1 and p.left or p.right)) end end
  for x=-r,r do local dy=math.floor(ry*math.sqrt(math.max(0,1-(x/r)^2))); for yy=0,dy do pp(img,cx+x,topY+h+yy,(x<0) and p.left or p.right) end end
  for y=-ry,ry do local dx=math.floor(r*math.sqrt(math.max(0,1-(y/ry)^2))); for x=-dx,dx do pp(img,cx+x,topY+y,p.top) end end
  pline(img,cx-r,topY,cx-r,topY+h,p.stroke); pline(img,cx+r,topY,cx+r,topY+h,p.stroke)
  for y=-ry,ry do local dx=math.floor(r*math.sqrt(math.max(0,1-(y/ry)^2))); pp(img,cx-dx,topY+y,p.stroke); pp(img,cx+dx,topY+y,p.stroke) end
  for x=-r,r do local dy=math.floor(ry*math.sqrt(math.max(0,1-(x/r)^2))); pp(img,cx+x,topY+h+dy,p.stroke) end
  return J({ cylinder=true, cx=cx, top=topY })
end)
"""
)

_POLY = (
    _ISO
    + """
return editCel(function(img, s)
  polyfill(img, PTS, app.pixelColor.rgba(R,G,B,A)); return J({ filled=#PTS })
end)
"""
)

_RECESS = (
    _ISO
    + """
return editCel(function(img, s)
  if #PTS ~= 4 then error("iso_recessed_panel needs exactly 4 corner points (a face)") end
  local cx,cy=0,0; for _,q in ipairs(PTS) do cx=cx+q[1];cy=cy+q[2] end; cx=cx/4;cy=cy/4
  local function ins(t) local o={}; for i,q in ipairs(PTS) do o[i]={q[1]+(cx-q[1])*t,q[2]+(cy-q[2])*t} end; return o end
  polyfill(img, ins(0.10), app.pixelColor.rgba(214,220,228,255))
  polyfill(img, ins(0.22), app.pixelColor.rgba(30,30,36,255))
  local h=ins(0.22); for i=1,4 do local a=h[i];local b=h[(i%4)+1]; pline(img,a[1],a[2],b[1],b[2],app.pixelColor.rgba(8,8,10,255)) end
  return J({ recessed=true })
end)
"""
)


def _points_lua(points) -> str:
    try:
        return "{" + ",".join(f"{{{int(p[0])},{int(p[1])}}}" for p in points) + "}"
    except (TypeError, KeyError, IndexError, ValueError):
        raise ToolError("points must be a list of [x, y] pairs") from None


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Draw isometric box"))
    @previewable
    def draw_iso_box(
        center_x: int,
        center_y: int,
        half_width: int,
        height: int,
        color: str,
        file: str | None = None,
    ) -> dict:
        """Draw a 2:1 isometric box. The footprint diamond is centered at
        (center_x, center_y) with the given ``half_width`` (full tile width =
        2×half_width), rising ``height`` px. Top/left/right faces are auto-shaded
        from ``color`` (#rrggbb, light from top-left) with stroke + highlight.
        Returns the top/SE/SW face corner polygons so you can attach recessed ports
        or details. One undo step. Headless: pass ``file``."""
        r, g, b, _ = parse_color(color)
        body = (
            lua_locals(
                CX=int(center_x),
                CY=int(center_y),
                HW=int(half_width),
                HT=int(height),
                R=r,
                G=g,
                B=b,
            )
            + _BOX
        )
        return run(body, mutates=True, undo_label="Iso box", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw isometric cylinder"))
    @previewable
    def draw_iso_cylinder(
        center_x: int, top_y: int, radius: int, height: int, color: str, file: str | None = None
    ) -> dict:
        """Draw a vertical isometric cylinder (tank/silo/chimney): top ellipse +
        shaded body + front rim, auto-shaded from ``color``. ``top_y`` is the top of
        the body. One undo step. Headless: pass ``file``."""
        r, g, b, _ = parse_color(color)
        body = (
            lua_locals(
                CX=int(center_x), TY=int(top_y), RAD=int(radius), HT=int(height), R=r, G=g, B=b
            )
            + _CYL
        )
        return run(body, mutates=True, undo_label="Iso cylinder", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Fill polygon"))
    @previewable
    def fill_polygon(points: list, color: str, file: str | None = None) -> dict:
        """Scanline-fill an arbitrary polygon given ``points`` (a list of [x, y]
        pairs, in order). ``color`` is #rrggbb or #rrggbbaa. One undo step.
        Headless: pass ``file``."""
        if not points or len(points) < 3:
            raise ToolError("need at least 3 points")
        r, g, b, a = parse_color(color)
        body = f"local PTS={_points_lua(points)}\n" + lua_locals(R=r, G=g, B=b, A=a) + _POLY
        return run(body, mutates=True, undo_label="Fill polygon", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Iso recessed panel"))
    @previewable
    def iso_recessed_panel(points: list, file: str | None = None) -> dict:
        """Draw a recessed docking socket/port on an isometric face — a light lit
        lip framing a dark recessed interior. ``points`` = the 4 corner [x, y] pairs
        of a face (e.g. the ``face_se`` returned by draw_iso_box). This is the
        consistent I/O-port style. One undo step. Headless: pass ``file``."""
        if not points or len(points) != 4:
            raise ToolError("iso_recessed_panel needs exactly 4 corner points (a face)")
        body = f"local PTS={_points_lua(points)}\n" + _RECESS
        return run(body, mutates=True, undo_label="Iso recessed panel", file=file)
