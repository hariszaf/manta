#!/usr/bin/env python

"""
The clustering algorithm works in several steps. First, an empty adjacency matrix is instantiated.
Then, the following steps are carried out until sparsity has stabilized:

1. Raise the matrix to power 2
2. Normalize matrix by absolute maximum value
3. Add 1 / value for each value in matrix
4. Normalize matrix by absolute maximum value
5. Calculate error by subtracting previous matrix from current matrix
6. If error threshold is reached, the algorithm stops

The generated score matrices and flow matrices are then supplied to the centrality function.
The centrality of an edge is calculated by the value of an edge in the matrix.
Hence, this does not imply that an edge had a large effect on other edges;
rather, it implies that it was affected by many of the diffusion processes during the iterations.

These centrality scores are then tested for their robustness using the functions in bootstrap_centrality.
As the absolute value of the scores is irrelevant,
only the ID of the edge (negative or positive hub) and the p-value is returned.
"""

__author__ = 'Lisa Rottjers'
__email__ = 'lisa.rottjers@kuleuven.be'
__status__ = 'Development'
__license__ = 'Apache 2.0'


import networkx as nx
import numpy as np
from sklearn.cluster import DBSCAN, KMeans
import sys
from manta.perms import perm_graph, diffusion
from scipy.stats import binom_test


def cluster_graph(graph, limit, max_clusters, min_clusters, iterations,
                  cluster='KMeans'):
    """
    Takes a networkx graph
    and carries out network clustering until
    sparsity results converge. Directionality is ignored;
    if weight is available, this is considered during the diffusion process.


    The min / max values that are the result of the diffusion process
    are used as a centrality measure and define positive as well as negative hub species.

    Parameters
    ----------
    :param graph: Weighted, undirected networkx graph.
    :param limit: Percentage in error decrease until matrix is considered converged.
    :param max_clusters: Maximum number of clusters to evaluate in K-means clustering.
    :param min_clusters: Minimum number of clusters to evaluate in K-means clustering.
    :param iterations: If algorithm does not converge, it stops here.
    :param cluster: Algorithm for clustering of score matrix.
    :return: NetworkX graph, score matrix and diffusion matrix.
    """
    adj_index = dict()
    for i in range(len(graph.nodes)):
        adj_index[list(graph.nodes)[i]] = i
    rev_index = {v: k for k, v in adj_index.items()}
    # next part is to define clusters of the adj matrix
    # cluster number is defined through gap statistic
    # max cluster number to test is by default 5
    # define topscore and bestcluster for no cluster
    scoremat, memory, diffs = diffusion(graph=graph, limit=limit, iterations=iterations)
    bestcluster = None
    # the randomclust is a random separation into two clusters
    # if K-means can't beat this, the user is given a warning
    # select optimal cluster by sparsity score
    if not memory:
        bestcluster = cluster_hard(graph, rev_index, scoremat, max_clusters, min_clusters, cluster=cluster)
    if memory:
        bestcluster = cluster_fuzzy(graph, rev_index, diffs, max_clusters, min_clusters, cluster=cluster)
    clusdict = dict()
    for i in range(len(graph.nodes)):
        clusdict[list(graph.nodes)[i]] = int(bestcluster[i])
    nx.set_node_attributes(graph, values=clusdict, name='cluster')
    return graph, scoremat


def central_edge(graph, percentile, permutations, error):
    """
    The min / max values that are the result of the diffusion process
    are used as a centrality measure and define positive as well as negative hub associations.

    If the permutation number is set to a value above 0, the centrality values are tested against permuted graphs.

    The fraction of positive edges and negative edges is based on the ratio between
    positive and negative weights in the network.

    Hence, a network with 90 positive weights and 10 negative weights will have 90% positive hubs returned.

    Parameters
    ----------
    :param graph: NetworkX graph of a microbial association network.
    :param percentile: Determines percentile of hub species to return.
    :param permutations: Number of permutations to carry out. If 0, no permutation test is done.
    :param error: Fraction of edges to rewire for reliability metric.
    :return: Networkx graph with hub ID / p-value as node property.
    """
    scoremat = diffusion(graph, iterations=3, norm=False)[0]
    negthresh = np.percentile(scoremat, percentile)
    posthresh = np.percentile(scoremat, 100-percentile)
    neghubs = list(map(tuple, np.argwhere(scoremat <= negthresh)))
    poshubs = list(map(tuple, np.argwhere(scoremat >= posthresh)))
    adj_index = dict()
    for i in range(len(graph.nodes)):
        adj_index[list(graph.nodes)[i]] = i
    if permutations > 0:
        score = perm_graph(graph, scoremat, percentile=percentile, permutations=permutations,
                           pos=poshubs, neg=neghubs, error=error)
    # need to make sure graph is undirected
    graph = nx.to_undirected(graph)
    # initialize empty dictionary to store edge ID
    edge_vals = dict()
    edge_scores = dict()
    # need to convert matrix index to node ID
    for edge in neghubs:
        node1 = list(graph.nodes)[edge[0]]
        node2 = list(graph.nodes)[edge[1]]
        edge_vals[(node1, node2)] = 'negative hub'
        if permutations > 0:
            edge_scores[(node1, node2)] = score[(adj_index[node1], adj_index[node2])]
    for edge in poshubs:
        node1 = list(graph.nodes)[edge[0]]
        node2 = list(graph.nodes)[edge[1]]
        edge_vals[(node1, node2)] = 'positive hub'
        if permutations > 0:
            edge_scores[(node1, node2)] = score[(adj_index[node1], adj_index[node2])]
    nx.set_edge_attributes(graph, values=edge_vals, name='hub')
    if permutations > 0:
        nx.set_edge_attributes(graph, values=edge_scores, name='reliability score')


def central_node(graph):
    """
    Given a graph with hub edges assigned (see central_edge),
    this function checks whether a node is significantly more connected
    to edges with high scores than expected by chance.
    The p-value is calculated with a binomial test.
    Edge sign is ignored; hubs can have both positive and negative
    edges.
    :param graph: NetworkX graph with edge centrality scores assigned
    :return: NetworkX graph with hub centrality for nodes
    """
    edges = nx.get_edge_attributes(graph, "hub")
    hubs = list()
    for edge in edges:
        hubs.append(edge[0])
        hubs.append(edge[1])
    hubs = list(set(hubs))
    sighubs = dict()
    pvals = dict()
    for node in hubs:
        hub_edges = 0
        for edge in graph[node]:
            if 'hub' in graph[node][edge]:
                hub_edges += 1
        # given that some of the edges
        # this is compared to the total edge number of the node
        # probability is calculated by dividing total number of hub edges in graph
        # by total number of edges in graph
        pval = binom_test(hub_edges, len(graph[node]),
                          (len(edges)/len(graph.edges)), alternative='greater')
        if pval < 0.05:
            sighubs[node] = 'hub'
            pvals[node] = float(pval)
    nx.set_node_attributes(graph, values=sighubs, name='hub')
    nx.set_node_attributes(graph, values=pvals, name='hub p-value')


def sparsity_score(graph, clusters, rev_index):
    """
    Given a graph, and a list of cluster identities,
    this function calculates how many edges need to be cut
    to assign these cluster identities.
    Cuts through positively-weighted edges are penalized,
    whereas cuts through negatively-weighted edges are rewarded.
    The lowest sparsity score represents the best clustering.
    Because this sparsity score rewards cluster assignments
    that separate out negative hubs.
    This penalty ensures that nodes with some intra-cluster
    negative edges are still assigned to clusters where
    they predominantly co-occur with other cluster members.
    :param graph: NetworkX weighted, undirected graph
    :param clusters: List of cluster identities
    :param rev_index: Index matching node ID to matrix index
    :return: Sparsity score
    """
    # set up scale for positive + negative edges
    # the sparsity score scales from -1 to 1
    # 1 is the worst possible assignment,
    # all negative edges inside clusters and positive outside clusters
    # -1 is the best,
    # with clusters containing only positive edges
    cut_score = 1/len(graph.edges)
    sparsity = 0
    edges = list()
    for cluster_id in set(clusters):
        # get the set of edges that is NOT in either cluster
        node_ids = list(np.where(clusters == cluster_id)[0])
        node_ids = [rev_index.get(item, item) for item in node_ids]
        cluster = graph.subgraph(node_ids)
        edges.extend(list(cluster.edges))
        # penalize for having negative edges inside cluster
        weights = nx.get_edge_attributes(cluster, 'weight')
        for x in weights:
            if weights[x] < 0:
                sparsity += cut_score
            else:
                sparsity -= cut_score
    all_edges = list(graph.edges)
    cuts = list()
    for edge in all_edges:
        if edge not in edges and (edge[1], edge[0]) not in edges:
            # problem with cluster edges having swapped orders
            cuts.append(edge)
    for edge in cuts:
        cut = graph[edge[0]][edge[1]]['weight']
        if cut > 0:
            sparsity += cut_score
        else:
            sparsity -= cut_score
    return sparsity


def cluster_fuzzy(graph, rev_index, diffs, max_clusters, min_clusters, cluster='KMeans'):
    """
    If a memory effect is demonstrated to exist during
    matrix diffusion, the fuzzy clustering algorithm assigns
    cluster identity based on multiple diffusion steps.
    :param graph: NetworkX weighted, undirected graph
    :param rev_index: Index matching node ID to matrix index
    :param scores: List of cluster sparsity scores
    :param diffs: List of diffusion matrices
    :param max_clusters: Maximum cluster number
    :param min_clusters: Minimum cluster number
    :param cluster: Clustering method (only KMeans supported for now)
    :return: Vector with cluster assignments
    """
    difscores = list()
    topscores = list()
    for j in range(len(diffs)):
        scoremat = diffs[j]
        scores = list()
        if cluster == 'KMeans':
            for i in range(min_clusters, max_clusters + 1):
                clusters = KMeans(i).fit_predict(scoremat)
                score = sparsity_score(graph, clusters, rev_index)
                scores.append(score)
            topscore = int(np.argmin(scores)) + min_clusters
            sys.stdout.write('Iteration ' + str(j) +
                             ': lowest score for k=' + str(topscore) + ' clusters: ' + str(np.min(scores)) + '\n')
            sys.stdout.flush()
        difscores.append(scores[np.argmin(scores)])
        topscores.append(topscore)
    separating_iters = np.where(np.array(difscores) < -0.5)[0]
    # the -0.5 is an arbitrary quality threshold
    sys.stdout.write('Using the following iterations for fuzzy clustering: ' + str(separating_iters) + '\n')
    sys.stdout.flush()
    # these iterations are able to separate the cluster relatively well
    # can be used to identify fuzzy clusters
    topscore = topscores[separating_iters[-1]]
    centroids = list()
    sep_clusters = list()
    # we should skip the first iteration
    # the centroids of this iteration are very close
    # to centers of outlier clusters in following iterations
    for j in separating_iters[1:]:
        scoremat = diffs[j]
        if cluster == 'KMeans':
            sep_clusters.append(KMeans(topscores[j]).fit_predict(scoremat))
            clusters = KMeans(topscores[j]).fit(scoremat)
            centroids.append(clusters.cluster_centers_)
    # once we have the centroids, we need to map clusters to eachother
    # e.g.: cluster 1 from iter 1 may look more like cluster 4 from iter 2
    clusdict = dict.fromkeys(list(range(topscore)))
    for key in clusdict:
        clusdict[key] = dict.fromkeys(list(range(len(centroids)-1)))
        for val in clusdict[key]:
            clusdict[key][val] = list()
    core_centers = centroids[-1]
    for j in range(0, len(centroids)-1):
        iter_centers = centroids[j]
        # closest centroid is the mean value closest to 0
        for m in range(len(iter_centers)):
            iter = iter_centers[m]
            diff = list()
            for n in range(len(core_centers)):
                diff.append(abs(np.mean(iter-core_centers[n])))
            clusdict[(diff.index(min(diff)))][j].append(m)
    # with the centroid mapping from before,
    # we can see if taxa move to different centroids
    clusprobs = np.zeros(len(sep_clusters[-1]))
    for i in range(0, len(sep_clusters[-1])):
        for j in range(0, len(sep_clusters) - 1):
            if sep_clusters[j][i] in clusdict[sep_clusters[-1][i]][j]:
                clusprobs[i] += 1/(len(sep_clusters)-1)
    bestcluster = sep_clusters[-1]
    # where nodes change cluster assignment >50% of the time,
    # the cluster assigned is 'fuzzy'
    bestcluster[np.where(clusprobs < 0.5)] = 100
    return bestcluster



def cluster_hard(graph, rev_index, scoremat, max_clusters, min_clusters, cluster='KMeans'):
    """
    If no memory effects are demonstrated, clusters can be identified
    without fuzzy clustering.
    :param graph: NetworkX weighted, undirected graph
    :param rev_index: Index matching node ID to matrix index
    :param scores: List of cluster sparsity scores
    :param scoremat: Converged diffusion matrix
    :param max_clusters: Maximum cluster number
    :param min_clusters: Minimum cluster number
    :param cluster: Clustering method (only KMeans supported for now)
    :return: Vector with cluster assignments
    """
    randomclust = np.random.randint(2, size=len(scoremat))
    scores = list()
    scores.append(sparsity_score(graph, randomclust, rev_index))
    sys.stdout.write('Sparsity level for 2 clusters, randomly assigned labels: ' + str(scores[0]) + '\n')
    sys.stdout.flush()
    if cluster == 'KMeans':
        for i in range(min_clusters, max_clusters + 1):
            clusters = KMeans(i).fit_predict(scoremat)
            score = sparsity_score(graph, clusters, rev_index)
            sys.stdout.write('Sparsity level of k=' + str(i) + ' clusters: ' + str(score) + '\n')
            sys.stdout.flush()
            scores.append(score)
        topscore = int(np.argmin(scores)) + min_clusters - 1
        if topscore >= min_clusters:
            sys.stdout.write('Lowest score for k=' + str(topscore) + ' clusters: ' + str(np.min(scores)) + '\n')
            sys.stdout.flush()
        else:
            sys.stdout.write(
                'Warning: random clustering performed best. \n Setting cluster amount to minimum value. \n')
            sys.stdout.flush()
        bestcluster = KMeans(topscore).fit_predict(scoremat)
    else:
        sys.stdout.write(
            'Warning: only K-means clustering is supported at the moment. \n Setting cluster amount to minimum value. \n')
        sys.stdout.flush()
    return bestcluster