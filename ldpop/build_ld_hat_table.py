'''
Created on Jan 26, 2015

@author: jeffreyspence
'''


from compute_likelihoods import folded_likelihoods, NumericalError
from moran_model import MoranStates, makeFrozen, MoranRates
from moran_model_dk import MoranStatesDK
from compute_stationary import stationary

from multiprocessing import Pool
import cPickle as pickle
import argparse, logging, time


def getKey(num00, num01, num10, num11):
    key = {}
    key[(0,0)] = num00
    key[(0,1)] = num01
    key[(1,0)] = num10
    key[(1,1)] = num11
    key[(0,-1)] = 0
    key[(-1,0)] = 0
    key[(1,-1)] = 0
    key[(-1,1)] = 0
    #return frozenset(key.items())
    return makeFrozen(key)

#columns has the columns of the table (plus possibly extraneous things, but we just pull out what we want
def getRow(num00, num01, num10, num11, columns, rhos):
    toReturn = []
    for rho in rhos:
        key = getKey(num00, num01, num10, num11)
        toReturn.append(str(columns[rho][key]))
    return " ".join(toReturn)

# def getEpochDemoRates(argList):
#     states, popSize, theta = argList
#     return states.getDemoRates(theta=theta, popSize=popSize)

def get_states(n, exact):
    if exact:
        return MoranStates(n)
    else:
        return MoranStatesDK(n)


def getColumn(moranRates, rho, theta, popSizes, timeLens, init):
    try:
        return folded_likelihoods(moranRates, rho, theta, popSizes, timeLens, lastEpochInit=init)
    except NumericalError, err:
        print rho
        print err

def computeLikelihoods(n, exact, popSizes, theta, timeLens, rhoGrid, cores):   
    states = get_states(n, exact)
    rhoGrid = sorted(rhoGrid)   

    moranRates = MoranRates(states)
    
    # now make the pool
    executor = Pool(cores)
    
    # compute initial distributions and likelihoods
    prevInit = states.getUnlinkedStationary(popSize=popSizes[-1], theta=theta)
    ret = []
    #for rho, rates in reversed(zip(rhoGrid, lastRatesList)):
    for rho in reversed(rhoGrid):
        rates = moranRates.getRates(rho=rho, popSize=popSizes[-1], theta=theta)
        prevInit = stationary(Q=rates, init=prevInit, norm_order=float('inf'), epsilon=1e-2)
        ret.append(executor.apply_async(getColumn,
                                        (moranRates, rho, theta, popSizes, timeLens, prevInit)))

    ret = [states.ordered_log_likelihoods(result.get()) for result in ret]
    executor.close()
    executor.join()
    
    return [(rho, lik) for rho,lik in zip(rhoGrid, reversed(ret))]


#note this would be easy to change for an arbitrary lookup table gridding, but LDHat wants what it wants
def print_lookup_table(n, rhos, rho_string, theta, popSizes, timeLens, exact, numThreads, pickleFile=None):
    start = time.time()
    
    columns = {}    #indexed by values of rho
    
    minRho = rhos[0]
    
    # only use exact to compute rho > 0
    if exact and minRho == 0.0:
        rhos = rhos[1:]
    results = computeLikelihoods(n, exact, popSizes, theta, timeLens, rhos, numThreads)

    # use approx to compute rho == 0.0, because exact==approx and approx is faster
    if exact and minRho == 0.0:
        results = computeLikelihoods(n, False, popSizes, theta, timeLens, [0.0], numThreads) + results
        rhos = [0.0] + rhos

    if pickleFile is not None:
        pickle.dump( results, open(pickleFile, "wb" ) )

    for result in results:
        columns[result[0]] = result[1]
    #
    
    #we want this to truncate, I guess:
    halfn = int(n) / 2
    
    #nifty formula courtesy of LD hat.  Note we do want this truncation division, or whatever it's called
    numConfigs = 1 + halfn + halfn * (halfn - 1) * (halfn + 4 ) / 6 + (halfn - 1) * (halfn + 2) / 2
    
    #print it out, starting with header:
    
    print str(n) + " " + str(numConfigs)
    print "1 " + str(theta)
    print rho_string
    
    configsSoFar = 0
    #make all these configs then print them out
    for i in xrange(1, halfn + 1):
            for j in xrange(1, i + 1):
                for k in xrange(j, -1, -1):
                    configsSoFar += 1
                    hapMult11 = k
                    hapMult10 = j - k;
                    hapMult01 = i - k;
                    hapMult00 = n - i - j + k;
                    
                    print str(configsSoFar) + " # " + str(hapMult00) + " " + str(hapMult01) + " " + str(hapMult10) + " " + str(hapMult11) + " : " + getRow(hapMult00, hapMult01, hapMult10, hapMult11, columns, rhos)
    assert configsSoFar == numConfigs
    end = time.time()
    logging.info("Computed lookup table in %f seconds " % (end-start))
    


def epochTimesToIntervalLengths(epochTimes):
    if epochTimes[0] == 0:
        raise IOError("Your first epoch time point should not be zero!")
    epochLengths = list(epochTimes)
    totalTime = 0.
    for i in xrange(0, len(epochLengths)):
        epochLengths[i] = epochLengths[i] - totalTime
        totalTime += epochLengths[i]
    return epochLengths

def ldhelmet_to_rho_array(ldhelmetrhos):
    rho_args = ldhelmetrhos.split(",")
    rhos = [float(rho_args[0])]
    arg_idx = 1
    while(arg_idx < len(rho_args)):
        assert arg_idx + 1 < len(rho_args)
        step_size = float(rho_args[arg_idx])
        endingRho = float(rho_args[arg_idx+1])
        arg_idx += 2
        cur_rho = rhos[-1]
        while(cur_rho < endingRho-1e-13):   #these 1e-13 are to deal with the numeric issues inherent in these sort of floating point schemes.
            cur_rho += step_size
            rhos.append(cur_rho)
        if abs(cur_rho - endingRho) > 1e-13:
            print cur_rho
            print endingRho
            raise IOError("the LDHelmet Rhos you input are not so nice (stepsize should divide difference in rhos)")
    ldhelmet_rho_string = " ".join(rho_args)
    true_rho_string = " ".join([str(r) for r in rhos])
    return rhos, ldhelmet_rho_string, true_rho_string

#usage : python build_ld_hat_table <n> <minRho> <maxRho> <numRhos> <theta> <popsize1,popsize2,...> <0.0 = epochEndPoint1,...> <exact or inexact> <numCores == 1>
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--numHaps", type=int)
    parser.add_argument("--theta", type=float)
    parser.add_argument("--popSizes", type=str)
    parser.add_argument("--epochTimes", type=str)
    parser.add_argument("--approx", action="store_true")
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--ldHelmetRhos", type=str)
    parser.add_argument("--log", type=str)
    args = parser.parse_args()

    if args.log == ".":
        logging.basicConfig(level=logging.INFO)
    elif args.log is not None:
        logging.basicConfig(filename=args.log, level=logging.INFO)
    
    assert (args.popSizes is None) == (args.epochTimes is None)
    if args.popSizes is None:
        popSizes = [1]
        epochLengths = []
    else:
        popSizes = [float(i) for i in args.popSizes.split(",")]
        epochLengths = epochTimesToIntervalLengths([float(i) for i in args.epochTimes.split(",")])
    assert len(popSizes) == len(epochLengths)+1
    
    exact = not args.approx
    numCores = args.cores
    
    rhos, rho_string, true_rhos = ldhelmet_to_rho_array(args.ldHelmetRhos)
        
    print_lookup_table(args.numHaps, rhos, rho_string, args.theta, popSizes, epochLengths, exact, numCores)