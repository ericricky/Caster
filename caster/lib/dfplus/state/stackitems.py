'''
Created on Jun 7, 2015

@author: dave
'''
from dragonfly import Pause, ActionBase

from caster.lib import control
from caster.lib import settings


class StackItem:
    def __init__(self, type):
        assert type in [StackItemRegisteredAction.TYPE, 
                        StackItemSeeker.TYPE, 
                        StackItemAsynchronous.TYPE, 
                        StackItemConfirm.TYPE]
        self.type = type
        self.complete = False  # indicates whether it has been run already
        self.consumed = False  # indicates that an undo is unnecessary
        self.rspec = "default"
    def put_time_action(self):
        ''' this always happens at the time that the Stack item is placed in the Stack '''
class StackItemRegisteredAction(StackItem):
    TYPE = "raction"
    def __init__(self, registered_action, data, type=TYPE):
        StackItem.__init__(self, type)
        self.dragonfly_data = data
        self.base = registered_action.base
        self.rspec = registered_action.rspec
        self.rdescript = registered_action.rdescript
        self.rundo = registered_action.rundo
        self.show = registered_action.show
        self.preserved = []
    def execute(self):
        self.complete = True
        self.base.execute(self.dragonfly_data)
        # do presentation here
        self.clean()
    def clean(self):
        self.dragonfly_data = None
        self.base = None
    def preserve(self):# save spoken words
        if self.dragonfly_data is not None:
            self.preserved = [x[0] for x  in self.dragonfly_data["_node"].results]
            return True
        return False
    def get_preserved(self):
        return self.preserved
    def put_time_action(self):
        self.preserve()
        if settings.SETTINGS["miscellaneous"]["status_window_enabled"] and self.show:
            control.nexus().intermediary.text(self.rdescript)
class StackItemSeeker(StackItemRegisteredAction):
    TYPE = "seeker"
    def __init__(self, seeker, data, type=TYPE):
        StackItemRegisteredAction.__init__(self, seeker, data, type)
        if self.type==StackItemSeeker.TYPE: self.back = self.copy_direction(seeker.back)
        self.forward = self.copy_direction(seeker.forward)
        self.spoken = {}
        self.eaten_rspec = {}
    
    @staticmethod
    def copy_direction(cls):
        result = None
        if cls != None:
            result = []
            for i in range(0, len(cls)):
                cl = cls[i].copy()
                cl.number(i)
                result.append(cl)
        return result
    def executeCL(self, cl):# the return value is whether to terminate an AsynchronousAction
        action = cl.result.f
        if action is None:
            return False
        elif isinstance(action, ActionBase):
            action.execute(cl.dragonfly_data)
            return False
        else:
            # it's a function object, so get the parameters, if any
            level = cl.index
            fnparams = cl.result.parameters
            if cl.result.use_spoken:
                fnparams = self.spoken[level]
            if cl.result.use_rspec:
                fnparams = self.eaten_rspec[level]
            if fnparams is None:
                return action()
            else:
                return action(fnparams)
            
            
    def eat(self, level, stack_item):
        self.spoken[level] = stack_item.preserved
        self.eaten_rspec[level] = stack_item.rspec
    def clean(self):
        # save whatever data you need here
        StackItemRegisteredAction.clean(self)
        if self.back is not None: 
            for cl in self.back:
                cl.dragonfly_data = None
        if self.forward is not None: 
            for cl in self.forward:
                cl.dragonfly_data = None
    def fillCL(self, cl, cs):
        cl.result = cs
        cl.dragonfly_data = self.dragonfly_data
    def execute(self, unused=None):
        self.complete = True
        c = []
        if self.back is not None: c += self.back
        if self.forward is not None: c += self.forward
        for cl in c:
            self.executeCL(cl)
        self.clean()
    def satisfy_level(self, level_index, is_back, stack_item):
        direction = self.back if is_back else self.forward
        cl = direction[level_index]
        if not cl.satisfied:
            if stack_item is not None:
                for cs in cl.sets:
                    # stack_item must have a spec
                    if stack_item.rspec in cs.specTriggers:
                        cl.satisfied = True
                        self.fillCL(cl, cs)
                        break
            if not cl.satisfied:  # if still not satisfied, do default
                cl.satisfied = True
                self.fillCL(cl, cl.sets[0])
    def get_index_of_next_unsatisfied_level(self):
        for i in range(0, len(self.forward)):
            cl = self.forward[i]
            if not cl.satisfied:
                return i
        return -1
class StackItemAsynchronous(StackItemSeeker):
    TYPE = "continuer"
    def __init__(self, continuer, data, type=TYPE):
        StackItemSeeker.__init__(self, continuer, data, type)
        self.back = None
        self.closure = None
        self.fillCL(self.forward[0], self.forward[0].sets[0]) # set context set and dragonfly data
        self.repetitions = continuer.repetitions
        self.time_in_seconds = continuer.time_in_seconds
        self.blocking = continuer.blocking
    def satisfy_level(self, level_index, is_back, stack_item):  # level_index and is_back are unused here, but left in for compatibility
        cl = self.forward[0]
        if not cl.satisfied:
            if stack_item is not None:
                cs = cl.sets[0]
                if stack_item.rspec in cs.specTriggers:  # stack_item must have a spec
                    cl.satisfied = True
    def get_triggers(self):
        return self.forward[0].sets[0].specTriggers
    def execute(self, success):  # this method should be what deactivates the continuer
        '''
        There are three ways this can be triggered: success, timeout, and cancel.
        Success and timeout are in the closure. Cancels are handled in the Stack.
        Waiting commands should only be run on success.
        '''
        self.complete = True
        control.nexus().timer.remove_callback(self.closure)
        if self.base is not None:# finisher
            self.base.execute()
        StackItemSeeker.clean(self)
        self.closure = None
        if success:
            control.nexus().state.run_waiting_commands()  # @UndefinedVariable
        else:
            control.nexus().state.unblock()  # @UndefinedVariable
    def begin(self):
        '''here pass along a closure to the timer multiplexer'''
        eCL = self.executeCL
        cl = self.forward[0]
        r = self.repetitions
        c = {"value":0}  # count
        e = self.execute
        def closure():
            terminate = eCL(cl)
            if terminate:
                e(terminate)
                
            elif r != 0:  # if not run forever
                c["value"] += 1
                if c["value"] == r:
                    e(False)
        self.closure = closure
        control.nexus().timer.add_callback(self.closure, self.time_in_seconds)
        self.closure()

class StackItemConfirm(StackItemAsynchronous):
    TYPE = "confirm"
    def __init__(self, confirm, data, type=TYPE):
        StackItemAsynchronous.__init__(self, confirm, data, type)
        self.base = Pause("50") + confirm.base # TODO: fix this race condition
        self.rspec = confirm.rspec
        self.hmc_response = 0
        
    def execute(self, success):
        if self.mutable_integer["value"]==1:
            self.base.execute(self.dragonfly_data)
        self.base = None
        StackItemAsynchronous.execute(self, success)
        
#     def receive_hmc_response(self, data):
#         self.hmc_response = data
    
    def shared_state(self, mutable_integer):
        self.mutable_integer = mutable_integer
        
        
        