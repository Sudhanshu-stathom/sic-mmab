import numpy as np

class PlayerStrategy():
    
    def __init__(self, narms, T):
        self.T = T # horizon
        self.t = 0 # current timestep
        self.K = narms # number of arms
        self.means = np.zeros(narms) # empirical means
        self.B = np.inf*np.ones(narms) # represents the confidence interval
        self.npulls = np.zeros(narms) # number of pulls for each arm

class SynchComm(PlayerStrategy):
    """
    SynchComm strategy
    """
    
    
    def __init__(self, narms, T=10, verbose=False):
        PlayerStrategy.__init__(self, narms, T)
        self.K0 = narms
        self.name = 'SynchComm'
        self.ext_rank = -1 # -1 until known
        self.int_rank = 0
        self.M = 1
        self.T0 = np.ceil(self.K*np.e*np.log(T))
        self.last_action = np.random.randint(self.K)
        self.phase = 'fixation'
        self.t_phase = 0
        self.round_number = 0
        self.last_phase_stats = np.zeros(self.K)
        self.active_arms = np.arange(0, self.K)
        self.sums = np.zeros(self.K)
        self.verbose = verbose
    
    def play(self):
        """
        return arm to pull
        """
        
        # fixation phase
        if self.phase=='fixation':
            if self.ext_rank==-1: # still trying to fix to an arm
                return np.random.randint(self.K)
            else: # sequential hopping
                return self.ext_rank
        
        # estimation phase
        if self.phase == 'estimation':
            if self.t <= self.T0 + 2*self.ext_rank: # waiting its turn to sequential hop
                return self.ext_rank
            else: # sequential hopping
                return (self.last_action+1)%self.K
                
        if self.phase == 'exploration':
            last_index = np.where(self.active_arms == self.last_action)[0][0]
            return self.active_arms[(last_index+1)%self.K]
        
        if self.phase == 'communication':
            if (self.t_phase < (self.int_rank+1)*(self.M-1)*self.K*(self.round_number+2) and (self.t_phase >= (self.int_rank)*(self.M-1)*self.K*(self.round_number+2))): # your turn to communicate
                # determine the number of the bit to send, the channel and the player
                
                t0 = self.t_phase % ((self.M-1)*self.K*(self.round_number+2)) # the actual time step in the communication phase (while giving info)
                b = (int)(t0 % (self.round_number+2)) # the number of the bit to send
                
                k0 = (int)(((t0-b)/(self.round_number+2))%self.K) # the arm to send
                k = self.active_arms[k0]
                if (((int)(self.last_phase_stats[k])>>b)%2): # has to send the bit
                    j = (t0-b-(self.round_number+2)*k0)/((self.round_number+2) * self.K) # the player to send
                    j = (int)(j + (j>= self.int_rank))
                    #print('Communicate bit {} about arm {} at player on arm {} by player {} at timestep {}'.format(b, k, self.active_arms[j], self.ext_rank, self.t_phase))
                    return self.active_arms[j]
                else:
                    return self.active_arms[self.int_rank]
                
            else:
                return self.active_arms[self.int_rank]
        
        if self.phase == 'exploitation':
            return self.last_action
            
        
    def update(self, play, obs):
        """
        Y = obs[0]
        C = obs[1]
        """
        self.last_action = play
        
        if self.phase == 'fixation':
            if self.ext_rank==-1:
                if not(obs[1]): # succesfully fixed
                    self.ext_rank = play
                    
            # phase change
            if self.t == self.T0:
                self.phase = 'estimation' # estimation of M
                self.last_action = self.ext_rank
            
                    
        elif self.phase == 'estimation':
            if obs[1]: # collision with a player
                if self.t <= self.T0 + 2*self.ext_rank: # it also increases the internal rank at the same time
                    self.int_rank += 1
                self.M += 1
                
            if self.t == self.T0 + 2*self.K:
                self.phase = 'exploration'
                self.t_phase = 0
                self.round_number = (int)(np.ceil(np.log2(self.M))) # we actually not start at the phase p=1 to speed up the exploration
                    
        elif self.phase == 'exploration':
            self.last_phase_stats[play] += obs[0]
            self.sums[play] += obs[0]
            self.t_phase += 1
            
            if self.t_phase == (2<<self.round_number) * self.K: # end of exploration round
                self.phase = 'communication'
                self.t_phase = 0
                
            
        elif self.phase == 'communication':
                # reception case
            if (self.t_phase >= (self.int_rank+1)*(self.M-1)*self.K*(self.round_number+2) or (self.t_phase < (self.int_rank)*(self.M-1)*self.K*(self.round_number+2))):
                if obs[1]:
                    t0 = self.t_phase % ((self.M-1)*self.K*(self.round_number+2)) # the actual time step in the communication phase (while giving info)
                    b = (int)(t0 % (self.round_number+2)) # the number of the bit to send

                    k0 = (int)(((t0-b)/(self.round_number+2))%self.K) # the channel to send
                    k = self.active_arms[k0]
                
                    self.sums[k] += ((2<<b)>>1)
                    
            
            self.t_phase += 1
            
            if (self.t_phase == (self.M)*(self.M-1)*self.K*(self.round_number+2) or self.M==1):
                # end of the communication phase
                # all the updates to do
                for k in self.active_arms:
                    self.npulls[k] += (2<<self.round_number)*self.M
                
                b_up = self.sums[self.active_arms]/self.npulls[self.active_arms] + np.sqrt(2*np.log(self.T)/(self.npulls[self.active_arms]))
                b_low = self.sums[self.active_arms]/self.npulls[self.active_arms] - np.sqrt(2*np.log(self.T)/(self.npulls[self.active_arms]))
                reject = []
                accept = []
                    
                for i, k in enumerate(self.active_arms):
                    better = np.sum(b_low > (b_up[i]))
                    worse = np.sum(b_up < b_low[i])
                    if better >= self.M:
                        reject.append(k)
                        if self.verbose:
                            print('player {} rejected arm {} at round {}'.format(self.ext_rank, k, self.round_number))
                    if worse >= (self.K - self.M):
                        accept.append(k)
                        if self.verbose:
                            print('player {} accepted arm {} at round {}'.format(self.ext_rank, k, self.round_number))
                for k in reject:
                    self.active_arms = np.setdiff1d(self.active_arms, k)
                for k in accept:
                    self.active_arms = np.setdiff1d(self.active_arms, k)
                self.M -= len(accept)
                self.K -= (len(accept)+len(reject))
                    
                    
                if len(accept)>self.int_rank:
                    self.phase = 'exploitation'
                    if self.verbose:
                        print('player {} starts exploiting arm {}'.format(self.ext_rank, accept[self.int_rank]))
                    self.last_action = accept[self.int_rank]
                else:
                    self.phase = 'exploration'
                    self.int_rank -= len(accept)
                    self.last_action = self.active_arms[self.int_rank]
                    self.round_number += 1
                    self.last_phase_stats = np.zeros(self.K0)
                    self.t_phase = 0
                        
                        
        self.t += 1
        
class MCTopM(PlayerStrategy):
    """
    MCTopM strategy introduced by Besson and Kaufmann
    """
    
    
    def __init__(self, narms, M, T=10):
        PlayerStrategy.__init__(self, narms, T)
        self.name = 'MCTopM'
        self.last_action = np.random.randint(narms)
        self.C = False
        self.s = False
        self.bestM = np.arange(0, narms)
        self.M = M
        self.b = np.copy(self.B)
        self.previous_b = np.copy(self.B)
    
    def play(self):
        """
        return arm to pull
        """
        
        if self.last_action not in self.bestM:      # transition 3 or 5
            action = np.random.choice(np.intersect1d(self.bestM, np.nonzero(self.previous_b <= self.previous_b[self.last_action])))
            self.s = False
        elif (self.C and not(self.s)): # collision and not fixed
            action = np.random.choice(self.bestM)
            self.s = False
        else:                   # tranistion 1 or 4
            action = self.last_action
            self.s = True
        
        return action
    
    def update(self, play, obs):
        self.last_action = play
        self.C = obs[1]
        self.t += 1
        self.means[play] = (self.npulls[play]*self.means[play] + obs[0])/(self.npulls[play] + 1)
        self.npulls[play] += 1
        self.B[play] = np.sqrt(np.log(self.T)/(2*self.npulls[play]))
        
        self.previous_b = np.copy(self.b)
        self.b = self.means + self.B
        self.bestM = np.argpartition(-self.b, self.M)[:self.M]
        
class MusicalChairs(PlayerStrategy):
    """
    Musical charis strategy introduced by Rosenski
    """
    
    
    def __init__(self, narms, T=10, delta=0.1):
        PlayerStrategy.__init__(self, narms, T)
        self.name = 'SynchComm'
        self.M = 1
        self.T0 = np.ceil(np.max([narms*np.log(2*narms*narms*T)/2, 16*narms*np.log(4*narms*narms*T)/(delta*delta), narms*narms*np.log(2*T)/0.02]))
        self.phase = 'exploration'
        self.fixed = -1
        self.bestM = None
        self.colls = 0
        
    def play(self):
        if self.phase == 'exploration':
            return np.random.randint(self.K)
        elif self.phase == 'fixation':
            return np.random.choice(self.bestM)
        else:
            return self.fixed          
        
    def update(self, play, obs):
        self.t += 1
        if self.phase == 'exploration':
            if not(obs[1]):
                self.means[play] = (self.npulls[play]*self.means[play] + obs[0])/(self.npulls[play]+1)
                self.npulls[play] += 1
            else:
                self.colls += 1
            
            if self.t >= self.T0:
                self.phase = 'fixation'
                self.M = (int)(np.round(np.log((self.t - self.colls)/self.t)/(np.log(1 - 1/self.K))))+1
                self.bestM = np.argpartition(-self.means, self.M)[:self.M]
                
        elif self.phase == 'fixation':
            if not(obs[1]):
                self.phase = 'exploitation'
                self.fixed = play
            
        