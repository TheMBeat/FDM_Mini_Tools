"""Reuse membership only along paths certified not to cross a surface.

Distance to a closed triangle surface is 1-Lipschitz. Two endpoint balls,
shrunk by a conservative float32 roundoff guard, cover their entire edge
when their radii sum exceeds its length. Membership is constant along such
an edge; union-find composes this certificate. Uncertified edges never join.
"""
from array import array
import math


def roundoff_guard(magnitude,tolerance=.0001):
    magnitude=max(1.,abs(float(magnitude)))
    return max(float(tolerance),32*2.**(math.floor(math.log2(magnitude))-23))


def classify(vertices,triangles,eligible,nearest,outside,guard=.0001,on_nearest=None):
    count=len(vertices);eligible=bytearray(eligible)
    if len(eligible)!=count or not math.isfinite(guard) or guard<=0:raise ValueError('Invalid containment proof input')
    parent=array('i',range(count));rank=bytearray(count);distance=array('d',[0.])*count
    queries=0;links=0
    for i,p in enumerate(vertices):
        if not eligible[i]:continue
        hit=nearest(p);queries+=1
        if hit and hit[0] is not None and hit[3] is not None and math.isfinite(hit[3]):
            distance[i]=max(0.,float(hit[3]))
        if on_nearest is not None:on_nearest(i,p,hit)
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for triangle in triangles:
        for a,b in ((triangle[0],triangle[1]),(triangle[1],triangle[2]),(triangle[2],triangle[0])):
            if not eligible[a] or not eligible[b] or distance[a]<=guard or distance[b]<=guard:continue
            ra,rb=root(a),root(b)
            if ra==rb:continue
            length=math.dist(vertices[a],vertices[b])
            if distance[a]+distance[b]<=length+2*guard:continue
            if rank[ra]<rank[rb]:ra,rb=rb,ra
            parent[rb]=ra
            if rank[ra]==rank[rb]:rank[ra]+=1
            links+=1
    groups={}
    for i,yes in enumerate(eligible):
        if not yes:continue
        r=root(i)
        if r not in groups:groups[r]=[i,1]
        else:
            group=groups[r];group[1]+=1
            if distance[i]>distance[group[0]]:group[0]=i
    inside=0;first_inside=None
    for i,size in groups.values():
        if not outside(vertices[i]):
            inside+=size
            if first_inside is None:first_inside=i
    return dict(inside=inside,first_inside=first_inside,eligible_vertices=sum(eligible),
        distance_queries=queries,winding_queries=len(groups),certified_links=links,guard_mm=guard)
