"""Cooperative recovery limits; exhaustion never certifies a route."""
from contextlib import contextmanager
from functools import wraps
import time

class SearchLimit(RuntimeError):pass

class RecoveryBudget:
    def __init__(self,cfg,clock=time.perf_counter):
        self.clock=clock
        self.total_seconds=max(0.,float(cfg.get('tree_recovery_seconds',20)))
        self.region_seconds=max(0.,float(cfg.get('tree_recovery_region_seconds',3)))
        self.total_queries=max(0,int(cfg.get('tree_recovery_queries',2400000)))
        self.region_queries=max(0,int(cfg.get('tree_recovery_region_queries',240000)))
        self.used=0.;self.queries=0;self.regions={};self.exhausted=[]
        self.priority=[];self.redundant=0
    @contextmanager
    def region(self,collider,point):
        key=tuple(float(c) for c in point)
        state=self.regions.setdefault(key,dict(seconds=0.,queries=0))
        self.current=state;self.started=self.clock()
        previous=getattr(collider,'_active_search_budget',None)
        collider._active_search_budget=self
        try:
            self.check();yield
        except SearchLimit as error:
            self.exhausted.append(dict(point=list(key),reason=str(error)))
            raise
        finally:
            elapsed=max(0.,self.clock()-self.started)
            state['seconds']+=elapsed;self.used+=elapsed
            collider._active_search_budget=previous
    def check(self):
        elapsed=max(0.,self.clock()-self.started)
        for exhausted,reason in (
            (self.used+elapsed>=self.total_seconds,'search_global_time_budget'),
            (self.queries>=self.total_queries,'search_global_work_budget'),
            (self.current['seconds']+elapsed>=self.region_seconds,'search_region_time_budget'),
            (self.current['queries']>=self.region_queries,'search_region_work_budget')):
            if exhausted:raise SearchLimit(reason)
        self.queries+=1;self.current['queries']+=1
    def summary(self):
        return dict(seconds=self.used,work_checks=self.queries,global_limit_seconds=self.total_seconds,
                    region_limit_seconds=self.region_seconds,exhausted=self.exhausted,
                    priorities=self.priority,redundant_contacts_omitted=self.redundant,
                    cooperative=True,collision_limits_unchanged=True)

def contact_budget(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        point=args[0] if args else kwargs.get('record',kwargs.get('point'))
        collider=args[1] if len(args)>1 else kwargs['collider']
        budget=getattr(collider,'recovery_budget',None)
        if budget is None:return function(*args,**kwargs)
        location=point['point'] if isinstance(point,dict) else point
        try:
            with budget.region(collider,location):
                return function(*args,**kwargs)
        except SearchLimit as error:
            return None,dict(reasons={str(error):1},budget_exhausted=True,route_calls=0,
                             trials=0,diagnostic_counts_partial=True)
    return wrapped

def prioritize(collider,records,layer):
    from . import layer_islands
    diagnosis=layer_islands.diagnose(collider.shell_geometry,records,layer=layer,classification_only=True)
    categories={r['id']:('MANDATORY_ISLAND' if r.get('certain') and r['kind']=='NEW_ISLAND'
                  else 'CONDITIONAL_OVERHANG' if r.get('certain') and r['kind']=='ANCHORED_OVERHANG'
                  else 'UNCERTAIN') for r in diagnosis['points']}
    ranks={'MANDATORY_ISLAND':0,'UNCERTAIN':1,'CONDITIONAL_OVERHANG':2}
    rows=[dict(id=r['id'],category=categories[r['id']],support_removal_allowed=False) for r in records]
    return sorted(records,key=lambda r:(ranks[categories[r['id']]],r['point'][2],r['id'])),rows


def part_config(cfg,count):
    """Reserve equal recovery shares; total is per candidate, not per part."""
    if count<1:raise ValueError('Part count must be positive')
    return dict(cfg,tree_recovery_seconds=float(cfg.get('tree_recovery_seconds',20))/count,
                tree_recovery_queries=max(0,int(cfg.get('tree_recovery_queries',2400000)))//count)
