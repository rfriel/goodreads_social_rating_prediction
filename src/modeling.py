from scrape_GR_tools import *
from scrape_explore import *

import graphlab as gl

from collections import defaultdict

def collectAllComms(client, db_exclude={}, removeOutliers=True):
    allComms = []
    for name in client.database_names():
        if name[:28] == 'goodreads_explore_from_book_' and name[28:] not in db_exclude:
            print "Checking database '%s'" % name
            db = client[name]
            if db['comms'].count() != 1:
                print 'Comms collection malformed or empty: expected 1 record, found %d records' % db['comms'].count()
            else:
                comms = db['comms'].find_one()['comms']
                if len(comms) > 0:
                    for i, comm in enumerate(comms):
                        if len(comm) > 0:
                            allComms.append(comm)
                        else:
                            print "Comm %d in database '%s' was empty" % (i, name)
                print 'Database has %d comms (we now have %d in total)' % (len(comms), len(allComms))
            print ''
    print 'Finished collecting comms.  We have %d comms in total.  Pruning...\n' % len(allComms)

    allCommsPruned = []

    for i, comm1 in enumerate(allComms):
        deleteComm1 = False
        for j, comm2 in enumerate(allComms[i+1:]):
            if comm1 == comm2:
                print 'Comms %d and %d were identical; removing %d\n' % (i, j+(i+1), i)
                deleteComm1 = True
        if not deleteComm1:
            allCommsPruned.append(comm1)
    if removeOutliers:
        len_with_outliers = len(allCommsPruned)
        commSizes = [len(c) for c in allCommsPruned]

        commSizesMed = np.median(commSizes)
        commSizesStd = np.std(commSizes)
        allCommsPruned = [comm for comm, commSize in zip(allCommsPruned, commSizes)
                          if np.abs(commSize - commSizesMed) < 3*commSizesStd]
        print 'Removed %d outlier comms' % (len_with_outliers - len(allCommsPruned))
    print 'Began with %d comms, now have %d after pruning.' % (len(allComms), len(allCommsPruned))

    return allCommsPruned

def getCommsOfRaters(ratingsCollection, comms):
    booksToRaterComms = defaultdict(set)
    commDict = {uID: i for i, comm in enumerate(comms) for uID in comm}

    for j, userID in enumerate(commDict.keys()):
        userComm = commDict[userID]
        r = ratingsCollection.find_one({'userID': userID})
        if r is not None:
            for bookID in r['ratings'].keys():
                booksToRaterComms[int(bookID)].add(userComm)
    return booksToRaterComms


def makeRecommenderInputs(ratingsCollection, booksCollection, comms, booksToRaterComms, \
                          bookInclusionReviewThreshold, userInclusionReviewThreshold, \
                          timeSplit, cutoffDate=None):
    booksToInclude = set()
    usersToInclude = set()


    for b in booksCollection.find({'bookID': {'$in': booksToRaterComms.keys()}}):
        raterUIDs = set([int(uID) for uID in b['ratings'].keys()])
        if len(booksToRaterComms[b['bookID']]) >= 1 and len(raterUIDs) >= bookInclusionReviewThreshold:
            booksToInclude.add(b['bookID'])

    for r in ratingsCollection.find({'userID': {'$in': [uID for comm in comms for uID in comm]}}):
        ratingsField = r['ratings']
        ratedBIDs = {int(bID) for bID in filter(lambda k: ratingsField[k][0] != 0, ratingsField.keys())}
        if len(ratedBIDs & booksToInclude) >= userInclusionReviewThreshold:
            usersToInclude.add(r['userID'])

    '''
    for r in ratingsCollection.find({'userID': {'$in': list(usersToInclude)}}):
        ratedBIDs = set([int(bID) for bID in r['ratings'].keys()])
        if len(ratedBIDs & booksToInclude) < userInclusionReviewThreshold:
            usersToInclude.remove(r['userID'])

    for r in ratingsCollection.find():
        curUID = r['userID']
        if curUID in allCommIDs:
            usersToInclude.add(curUID)
        else:
            usersToExclude.add(curUID)
    print '%d books excluded.' % (booksCollection.count() - len(booksToInclude))
    print '%d books included.\n' % len(booksToInclude)

    print '%d users excluded.' % (ratingsCollection.count() - len(usersToInclude))
    print '%d users included.' % len(usersToInclude)
    '''

    commDict = {uID: i for i, comm in enumerate(comms) for uID in comm}

    glRatingDict = makeRatingDictForGL(ratingsCollection, commDict, booksToInclude, usersToInclude)
    glRatings = gl.SFrame(glRatingDict)

    # ratingCountsByBook = glRatings.groupby(['bookID'], gl.aggregate.COUNT('rating'))
    # npBookIDs = np.array(ratingCountsByBook['bookID'])
    # npRatingCounts = (np.array(ratingCountsByBook['Count']))
    # booksToInclude = {int(bID) for bID in npBookIDs[npRatingCounts >= bookInclusionReviewThreshold]}

    if not timeSplit:
        glRatingDict = makeRatingDictForGL(ratingsCollection, commDict, booksToInclude, usersToInclude)
        glRatings = gl.SFrame(glRatingDict)

        #glRatings = removeGlOutliers(glRatings)
        return glRatings
    else:
        glRatingDictTrain = makeRatingDictForGL(ratingsCollection, commDict, booksToInclude, usersToInclude, \
                                                cutoffDate, True)
        glRatingDictTest = makeRatingDictForGL(ratingsCollection, commDict, booksToInclude, usersToInclude, \
                                                cutoffDate, False)

        glRatingsTrain = gl.SFrame(glRatingDictTrain)
        glRatingsTest = gl.SFrame(glRatingDictTest)

        #glRatingsTrain = removeGlOutliers(glRatingsTrain)
        #glRatingsTest = removeGlOutliers(glRatingsTest)
        return glRatingsTrain, glRatingsTest

def removeGlOutliers(glRatings):
    commIndices = np.array(glRatings.groupby(['comm'], gl.aggregate.COUNT('rating')).sort('comm')['comm'])
    commSizes = np.array(glRatings.groupby(['comm'], gl.aggregate.COUNT('rating')).sort('comm')['Count'])

    commSizesMed = np.median(commSizes)
    commSizesStd = np.std(commSizes)
    outlierDict = {commIndex: np.abs(commSize - commSizesMed) < 3*commSizesStd for commIndex, commSize \
     in zip(commIndices, commSizes)}
    return outlierDict, glRatings[glRatings['comm'].apply(lambda x: outlierDict[x])]

def makeSocialModelInputs(glRatingsTrain):
    glCommMeansTrain = glRatingsTrain.groupby(['comm'], {'meanRatingByComm': gl.aggregate.MEAN('rating')})
    glCommBookMeansTrain = glRatingsTrain.groupby(['comm', 'bookID'], {'meanBookRatingByComm': gl.aggregate.MEAN('rating')})

    commMeansTrain = {}
    commBookMeansTrain = {}

    for row in glCommMeansTrain:
        commMeansTrain[row['comm']] = row['meanRatingByComm']

    for row in glCommBookMeansTrain:
        commBookMeansTrain[(row['bookID'], row['comm'])] = row['meanBookRatingByComm']

    # the former two objects returned contain the same information as the latter two

    # the 'gl' objects are graphlab SFrames, for use as input to a graphlab recommender

    # the other two are dicts of the form {(bookID, comm): rating}, which are much
    # faster to access than the SFrames.  this speeds up predictFromCommMeans
    # a great deal.
    return glCommMeansTrain, glCommBookMeansTrain, commMeansTrain, commBookMeansTrain

def degreesOfFreedomStats(glRatingsTrain):
    nTrainObs = glRatingsTrain.shape[0]
    if 'userID' in glRatingsTrain.column_names():
        nTrainUsers = len(glRatingsTrain['userID'].unique())
    else:
        nTrainUsers = len(glRatingsTrain['comm'].unique())
    nTrainItems = len(glRatingsTrain['bookID'].unique())

    print '%d observations\n%d users\n%d books\n' % (nTrainObs, nTrainUsers, nTrainItems)

    for n in range(1,10):
        print 'A recommender with %d factor(s) (plus linear terms) would use %.1f%% of the degrees of freedom present in the data.' \
        % (n-1, 100*(n*float(nTrainUsers + nTrainItems)) / nTrainObs)
        print '(%.1f observations per model degree of freedom)\n' % (nTrainObs/(n*float(nTrainUsers + nTrainItems)))

def predictFromCommMeans(bookIDs, commIDs, commMeansTrain, commBookMeansTrain, useBookMeans):
    predictedRatings = []
    for bID, comm in zip(bookIDs, commIDs):
        if useBookMeans and ((bID, comm) in commBookMeansTrain):
            predictedRatings.append(commBookMeansTrain[(bID, comm)])
        elif comm in commMeansTrain:
            predictedRatings.append(commMeansTrain[comm])
        else:
            # if community of input user doesn't appear in the training data at all,
            # then just use the average rating over all comms (note: compare to 'over all users'?)
            predictedRatings.append(sum(commMeansTrain.values())/len(commMeansTrain))
            #predictedRatings.append(-1)
    return np.array(predictedRatings)

class surprisePredWrapper():
    def __init__(self, surpriseModel):
        self.surpriseModel = surpriseModel
    def predict(self, glRatings):
        # line below gives a value of 0 to the predict method for the true rating
        # because we don't need the true ratings here to be correct, as they
        # will not be returned
        preds=[self.surpriseModel.predict(str(row['userID']),str(row['bookID']),0).est for row in glRatings]
        return preds


def mixedPred(glRatingsTestWithComm, commMeansTrain, commBookMeansTrain,\
              factorCommBookMeansTrain, rec_engine, rec_engine_comm, \
              numTrainRatings_Test, \
              commMeansOverBaseRec, socialRec, useBookMeans, meanWeight):
    predsBase = np.array(rec_engine.predict(glRatingsTestWithComm['bookID', 'userID']))
    if commMeansOverBaseRec:
        #
        predsComm = predictFromCommMeans(\
                                              glRatingsTestWithComm['bookID'],
                                              glRatingsTestWithComm['comm'],
                                              commMeansTrain, factorCommBookMeansTrain,
                                              True
                                               )
    elif socialRec:
        predsComm = np.array(rec_engine_comm.predict(glRatingsTestWithComm['bookID', 'comm'].rename({'comm':'userID'})))
    else:
        # predict community aggregates solely by retrieving relevant aggregates from a lookup table
        predsComm = predictFromCommMeans(\
                                              glRatingsTestWithComm['bookID'],
                                              glRatingsTestWithComm['comm'],
                                              commMeansTrain, commBookMeansTrain,
                                              useBookMeans
                                               )
    #adjWeights = 1#(np.abs(3.8 - predsBase) / np.max(np.abs(3.8 - predsBase)))
    #adjWeights = 1#np.max(adjWeights) - adjWeights
    #adjWeights=(100. - numTrainRatings_Test)/100.
    #adjWeights[adjWeights<0]=0
    #adjWeights = adjWeights**(0.25)
    #adjWeights = (numTrainRatings_Test < 120).astype(float)
    #adjWeights = 0.5*(numTrainRatings_Test<30) + 0.5*(numTrainRatings_Test < 150)

    adjXmax = 100.
    adjX = numTrainRatings_Test.copy()
    adjX[adjX>adjXmax] = adjXmax
    adjWeights = (adjX-(adjXmax/2))/adjXmax
    adjWeights = adjWeights / (max(adjWeights)-min(adjWeights))
    adjWeights = adjWeights - min(adjWeights)

    predsComm[predsComm<0] = predsBase[predsComm<0]
    #preds = (1-meanWeight)*predsBase + meanWeight*predsComm
    preds = (1-adjWeights*meanWeight)*predsBase + meanWeight*adjWeights*predsComm
    predRmse = rmse(preds, glRatingsTestWithComm['rating'].to_numpy())
    return preds, predRmse

def rmse(y_pred, y_true):
    sse = sum((np.array(y_pred) - np.array(y_true))**2)
    return np.sqrt(float(sse)/len(y_pred))
