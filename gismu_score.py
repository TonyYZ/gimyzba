#!/usr/bin/env python

# Lojban gismu candidate creation and evaluation script
# Version 0.5

# Copyright 2014 Riley Martinez-Lynch, except where
# Copyright 2012 Arnt Richard Johansen.
# Distributed under the terms of the GPL v3.

# Usage:
#
#   python gismu_score.py uan rakan ekspekt esper predpologa mulud
#

import sys
import re
import threading
import Queue

from optparse import OptionParser

from gismu_utils import C, V, LANGUAGE_WEIGHTS, \
  GismuGenerator, GismuScorer, GismuMatcher

from marshal import dump

VERSION = "v0.5"

DEFAULT_LANGUAGE_WEIGHTS = LANGUAGE_WEIGHTS['1995'] # as they appear in CLL

def main(words, params):

    if params.all_letters:
        (c, v) = (C, V)
    else:
        (c, v) = letters_for_words(words)

    # "In practice, we only scored forms that used the letters/phonemes in the
    #  source languages, which greatly reduced the computation."
    # (http://mail.lojban.org/lists/lojban-list/msg26536.html)

    shapes = re.split('\s*,\s*', params.shapes)
    candidate_iterator = GismuGenerator(c, v, shapes).iterator()

    print >>sys.stderr, "Generating candidates..."
    # pre-extracting candidates from the iterator is not needed downstream
    # but lets us inform the user how many candidates will be evaluated
    candidates = list(candidate_iterator)
    print >>sys.stderr, "%d candidates generated." % len(candidates)

    weights = [float(weight) for weight in re.split("\s*,\s*", params.weights)]

    scorer = GismuScorer(words, weights)
    if params.workers == 1:
        print >>sys.stderr, "Scoring candidates..."
        scores = compute_scores(candidates, scorer, params)
    else:
        print >>sys.stderr, \
          "Scoring candidates with %d workers..." % params.workers
        scores = compute_scores_threaded(candidates, scorer, params)

    print >>sys.stderr, "Sorting scores..."
    scores.sort(lambda x,y:cmp(y[0], x[0]))

    print >>sys.stderr, ""
    print >>sys.stderr, "10 first gismu candidates are:"
    print >>sys.stderr, ""
    for record in scores[:10]:
        print >>sys.stderr, record

    if params.gismu_list_path:
        print >>sys.stderr, "Reading list of gismu... "
        gismus = [line.strip() for line in file(params.gismu_list_path)]
        matcher = GismuMatcher(gismus)
        print >>sys.stderr, "Exluding candidates similar to existing gismu..."
        candidate = deduplicate_candidates(matcher, scores)
        if candidate == None:
            print >>sys.stderr, "No suitable candidates found."
        else:
            print >>sys.stderr, "The winner is....\n"
            print candidate.upper()

    if params.output_path:
        print >>sys.stderr, "\rDumping scores to %s" % params.output_path
        sink = open(params.output_path, 'w')
        dump(scores, sink)
        sink.close()

def letters_for_words(words):
    word_set = set([ l for word in words for l in list(word) ])
    return word_set.intersection(C), word_set.intersection(V)

def compute_scores(candidates, scorer, params):
    quiet = params.quiet
    scores = []
    for i, candidate in enumerate(candidates):
        score = compute_score(scorer, candidate)
        scores.append(score)
        if (not quiet) and (i % 100 == 0):
            print >>sys.stderr, "\010" * 9, # backspace
            print >>sys.stderr, i + 1,
    return scores

def compute_score(scorer, candidate):
    weighted_sum, language_scores = scorer.compute_score(candidate)
    return (weighted_sum, candidate, language_scores)

def compute_scores_threaded(candidates, scorer, params):
    input_queue = Queue.Queue()
    for candidate in candidates:
        input_queue.put(candidate)
    output_queue = Queue.Queue()

    workers = []
    for x in xrange(params.workers):
        worker = QueueWorker(input_queue, output_queue, scorer, params)
        worker.start()
        workers.append(worker)
    for worker in workers:
        worker.join()
    return read_scores_from_queue(output_queue)

def read_scores_from_queue(score_queue):
    scores = []
    queue_empty = False
    while not queue_empty:
        try:
            score = score_queue.get_nowait()
            scores.append(score)
        except Queue.Empty:
            queue_empty = True
    return scores

def deduplicate_candidates(matcher, scores):
    unique_candidate = None
    for (score, candidate, _) in scores:
        gismu = matcher.find_similar_gismu(candidate)
        if gismu == None:
            unique_candidate = candidate
            break
        else:
            print >>sys.stderr, \
              "Candidate '%s' too much like gismu '%s'." % (candidate, gismu)
    return unique_candidate

##

class QueueWorker(threading.Thread):

    def __init__(self, input_queue, output_queue, scorer, params):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.scorer = scorer
        self.params = params
        threading.Thread.__init__(self)

    def run(self):
        quiet = self.params.quiet
        i = 0
        while 1:
            candidate = self.read_input()
            if candidate == None:
                break
            self.process_input(candidate)

            i += 1
            if (not quiet) and (i % 100 == 0):
                print >>sys.stderr, "\010" * 9, # backspace
                print >>sys.stderr, i,

    def read_input(self):
        candidate = None
        try:
            candidate = self.input_queue.get(True, 2) # block for up to 2s
        except Queue.Empty:
            pass
        return candidate

    def process_input(self, candidate):
        weighted_sum, language_scores = self.scorer.compute_score(candidate)
        self.output_queue.put((weighted_sum, candidate, language_scores))

##

def check_weights_option(option, opt_str, value, parser):
    if re.match('(\d{4}|finprims)$', value):
        if value in LANGUAGE_WEIGHTS:
            print >>sys.stderr, "Using language weights from %s..." % value
            value = ",".join([ str(x) for x in LANGUAGE_WEIGHTS[value] ])
        else:
            raise ValueError("No weights registered for %d" % year)
    else:
        weights = re.split('\s*,\s*', value)
        if len(weights) < 2:
            raise ValueError("%s must include at least 2 values" % opt_str)
        [ check_weight_option(opt_str, weight) for weight in weights ]
    setattr(parser.values, option.dest, value)

def check_weight_option(opt_str, weight_string):
    error = False
    try:
        weight = float(weight_string)
        error = weight <= 0
    except:
        error = True
    if error:
        raise ValueError("Values for %s must be numbers greater than zero" % opt_str)

def check_shapes_option(option, opt_str, value, parser):
    shapes = re.split('\s*,\s*', value)
    for shape in shapes:
        if len(shape) < 4:
            raise ValueError("Value for %s must contain at least 4 letters" % opt_str)
        if not re.match('[cv]+$', shape, re.I):
            raise ValueError("Value for %s must consist only of 'c' and 'v'" % opt_str)
    setattr(parser.values, option.dest, value)

def validate_words(words, params):
    weight_count = len(re.split("\s*,\s*", params.weights))
    if len(words) != weight_count:
        raise ValueError("Expected %d words as input" % weight_count)
    for word in words:
        if len(word) < 2:
            raise ValueError("Input words must be at least two letters long")

if __name__ == '__main__':

    usage_fmt = "usage: %prog [ options ] { input words }"
    options = OptionParser(usage=usage_fmt, version="%prog " + VERSION)

    options.add_option("-q", "--quiet",
                       action="store_true", dest="quiet")

    options.add_option("-a", "--all-letters",
                       action="store_true", dest="all_letters")

    default_weights = ",".join([ str(x) for x in DEFAULT_LANGUAGE_WEIGHTS ])
    options.add_option("-w", "--weights",
                       default=default_weights, dest="weights",
                       type="string", action="callback",
                       callback=check_weights_option)

    options.add_option("-s", "--shapes",
                       default="ccvcv,cvccv", dest="shapes",
                       type="string", action="callback",
                       callback=check_shapes_option)

    options.add_option("-n", "--number-workers",
                       type="int", default="1", dest="workers")

    options.add_option("-d", "--deduplicate",
                       type="string", dest="gismu_list_path")

    options.add_option("-o", "--output",
                       type="string", dest="output_path")

    error = False

    try:
        (params, words) = options.parse_args()
        validate_words(words, params)
    except Exception, e: # NOTE: python 2.5 syntax for jython (sorry, python3!)
        print >>sys.stderr, "\n%s\n" % e
        error = True

    if error:
        options.print_help()
        print >>sys.stderr
        exit()

    main(words, params)

