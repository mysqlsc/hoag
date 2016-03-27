import numpy as np
from numpy import array, asarray, float64, int32, zeros
from scipy import linalg
from scipy.optimize.lbfgsb import _lbfgsb
from scipy.sparse import linalg as splinalg
from sklearn.metrics.pairwise import pairwise_kernels, euclidean_distances


def _minimize_lbfgsb(
    h_sol_approx, h_hessian, h_crossed, g_func_grad, g_cross, x0, bounds=None,
    lambda0=0., disp=None, maxcor=10, ftol=1e-24,
    maxiter=100, maxls=20, tolerance_decrease='exponential',
    callback=None):
    """
    Minimize a scalar function of one or more variables using the L-BFGS-B
    algorithm.
    Options
    -------
    disp : bool
       Set to True to print convergence messages.
    maxcor : int
        The maximum number of variable metric corrections used to
        define the limited memory matrix. (The limited memory BFGS
        method does not store the full g_func_grad but uses this many terms
        in an approximation to it.)
    factr : float
        The iteration stops when ``(f^k -
        f^{k+1})/max{|f^k|,|f^{k+1}|,1} <= factr * eps``, where ``eps``
        is the machine precision, which is automatically generated by
        the code. Typical values for `factr` are: 1e12 for low
        accuracy; 1e7 for moderate accuracy; 10.0 for extremely high
        accuracy.
    ftol : float
        The iteration stops when ``(f^k -
        f^{k+1})/max{|f^k|,|f^{k+1}|,1} <= ftol``.
    gtol : float
        The iteration will stop when ``max{|proj g_i | i = 1, ..., n}
        <= gtol`` where ``pg_i`` is the i-th component of the
        projected gradient.
    eps : float
        Step size used for numerical approximation of the jacobian.
    disp : int
        Set to True to print convergence messages.
    maxfun : int
        Maximum number of function evaluations.
    maxiter : int
        Maximum number of iterations.
    maxls : int, optional
        Maximum number of line search steps (per iteration). Default is 20.
    """
    m = maxcor
    factr = ftol / np.finfo(float).eps
    lambdak = lambda0

    x0 = asarray(x0).ravel()
    n, = x0.shape

    if bounds is None:
        bounds = [(None, None)] * n
    if len(bounds) != n:
        raise ValueError('length of x0 != length of bounds')
    # unbounded variables must use None, not +-inf, for optimizer to work properly
    bounds = [(None if l == -np.inf else l, None if u == np.inf else u) for l, u in bounds]

    if disp is not None:
        if disp == 0:
            iprint = -1
        else:
            iprint = disp

    nbd = zeros(n, int32)
    low_bnd = zeros(n, float64)
    upper_bnd = zeros(n, float64)
    bounds_map = {(None, None): 0,
                  (1, None): 1,
                  (1, 1): 2,
                  (None, 1): 3}
    for i in range(0, n):
        l, u = bounds[i]
        if l is not None:
            low_bnd[i] = l
            l = 1
        if u is not None:
            upper_bnd[i] = u
            u = 1
        nbd[i] = bounds_map[l, u]

    if not maxls > 0:
        raise ValueError('maxls must be positive.')

    x = array(x0, float64)
    wa = zeros(2*m*n + 5*n + 11*m*m + 8*m, float64)
    iwa = zeros(3*n, int32)
    task = zeros(1, 'S60')
    csave = zeros(1, 'S60')
    lsave = zeros(4, int32)
    isave = zeros(44, int32)
    dsave = zeros(29, float64)

    task[:] = 'START'

    epsilon_tol_init = 1e-3
    exact_epsilon = 1e-24
    if tolerance_decrease == 'exact':
        epsilon_tol = exact_epsilon
    else:
        epsilon_tol = epsilon_tol_init

    qk = None
    L_lambda = None
    g_func_old = np.inf

    if callback is not None:
        callback(x, lambdak)

    # n_eval, F = wrap_function(F, ())
    old_grads = []

    for it in range(1, maxiter):
        x0 = h_sol_approx(x0, lambdak, epsilon_tol)

        fhs = h_hessian(x0, lambdak)
        Hessfunc = splinalg.LinearOperator(
            shape=(x0.size, x0.size),
            matvec=lambda z: fhs(z))

        g_func, g_grad = g_func_grad(x0, lambdak)
        print('Cost: ', g_func)
        qk, success = splinalg.cg(Hessfunc, g_grad, x0=qk, tol=epsilon_tol)
        if success is False:
            raise ValueError

        # .. update hyperparameters ..
        grad_lambda = g_cross(x0, lambdak) - h_crossed(x0, lambdak).dot(qk)
        old_grads.append(linalg.norm(grad_lambda))

        old_lambdak = lambdak
        # pk = 0.8 * grad_lambda + 0.2 * old_grad_lambda
        pk = grad_lambda

        if L_lambda is None:
            if old_grads[-1] == 0:
                # decrease tolerance
                epsilon_tol *= 0.1
                continue
            L_lambda = 5 * linalg.norm(grad_lambda)

        step_size = (1./L_lambda)

        tmp = lambdak - step_size * pk
        lambdak = tmp

        # .. decrease accuracy ..

        # .. decrease accuracy ..
        old_epsilon_tol = epsilon_tol
        if tolerance_decrease == 'quadratic':
            epsilon_tol = epsilon_tol_init / ((it) ** 2.)
        elif tolerance_decrease == 'cubic':
            epsilon_tol = epsilon_tol_init / ((it) ** 3.)
        elif tolerance_decrease == 'exponential':
            epsilon_tol *= 0.5
        elif tolerance_decrease == 'exact':
            epsilon_tol = 1e-24
        else:
            raise NotImplementedError

        epsilon_tol = max(epsilon_tol, exact_epsilon)
        incr = linalg.norm(lambdak - old_lambdak)

        C = 1

        if g_func <= g_func_old + C * epsilon_tol + \
                old_epsilon_tol * (C + 1) * incr - (L_lambda / 2.) * incr * incr:
            # increase step size
            L_lambda *= .8
            print('increased step size')
        # elif g_func - epsilon_tol <= g_func_old + old_epsilon_tol:
        #     # do nothing
        #     print('do nothing')
        #     pass
        else:
            print('decrease step size')
            L_lambda *= 1.2

        norm_lambda = linalg.norm(pk)
        print(('it %s, pk: %s, lambda %s, epsilon: %s, ' +
              'L: %s, grad_lambda: %s') %
              (it, norm_lambda, lambdak, epsilon_tol, L_lambda,
               grad_lambda))
        g_func_old = g_func

        if callback is not None:
            callback(x0, lambdak)
        print()

    return x0, lambdak, 0


class KernelRidgeCV:

    def __init__(self, tolerance_decrease='exponential', alpha0=[0.0, 0.0],
                 max_iter=100):
        self.tolerance_decrease = tolerance_decrease
        self.alpha0 = alpha0
        self.max_iter = max_iter

    def fit(self, Xt, yt, Xh, yh, callback=None):
        x0 = np.zeros(Xt.shape[0])

        # def h_loss(x, lambdak):
        #     K = pairwise_kernels(
        #         Xt, gamma=np.exp(lambdak[0]),
        #         metric='rbf')
        #     return np.exp(lambdak[1]) * (x.dot(x) + 2 * x.dot(yt)) + \
        #         x.dot(K).dot(x)

        def h_sol_approx(x, lambdak, tol):
            # returns an approximate solution of the inner optimization
            K = pairwise_kernels(Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            (out, success) = splinalg.cg(
                K + np.exp(lambdak[1]) * np.eye(x0.size), yt, x0=x)
            if success is False:
                raise ValueError
            return out

        def h_hessian(w, lambdak):
            K = pairwise_kernels(Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            return lambda x: (K + np.exp(lambdak[1]) * np.eye(x.size)).dot(x)

        def h_crossed(x, lambdak):
            Kprime = -euclidean_distances(Xt, squared=True) * pairwise_kernels(
                            Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            deriv1 = np.exp(lambdak[0]) * Kprime.dot(x)
            deriv2 = np.exp(lambdak[1]) * x
            return np.array((deriv1, deriv2))

        def h_grad(x, lambdak):
            K = pairwise_kernels(Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            return K.dot(x) + np.exp(lambdak[1]) * x - yt

        # import numdifftools as nd
        # x1 = np.random.randn(x0.size)
        # h_cross_1 = nd.Jacobian(lambda x: h_grad(x1, [x[0], 0]))
        # print(h_cross_1([0.0]).ravel())
        # print(h_crossed(x1, [0, 0.0])[0])

        # h_hess_1 = nd.Jacobian(lambda x: h_grad(x, [0, 0]))
        # print(h_hess_1(x1).dot(x1))
        # print(h_hessian(x1, [0, 0])(x1))
        # 1/0

        def g(x, lambdak):
            K_pred = pairwise_kernels(Xh, Xt, gamma=np.exp(lambdak[0]),
                                      metric='rbf')
            pred = K_pred.dot(x)
            v = yh - pred
            return v.dot(v)

        def g_grad(x, lambdak):
            K_pred = pairwise_kernels(
                Xh, Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            pred = K_pred.dot(x)
            return - 2 * K_pred.T.dot(yh - pred)

        def g_cross(x, lambdak):
            K_pred = pairwise_kernels(
                Xh, Xt, gamma=np.exp(lambdak[0]), metric='rbf')
            K_pred_prime = -np.exp(lambdak[0]) * euclidean_distances(
                Xh, Xt, squared=True) * K_pred
            pred = K_pred.dot(x)
            v = yh - pred
            tmp = K_pred_prime.dot(x)
            return np.array((- 2 * tmp.dot(v), 0.0))


        # x_test = np.random.randn(x0.size)
        # from scipy.optimize import check_grad
        # r = check_grad(g, g_grad, x_test, self.alpha0, epsilon=1e-6)
        # print(r)
        # 1/0

        def g_func_grad(w, alpha):
            return (g(w, alpha), g_grad(w, alpha))

        opt = _minimize_lbfgsb(
            h_sol_approx, h_hessian, h_crossed, g_func_grad, g_cross, x0,
            callback=callback,
            tolerance_decrease=self.tolerance_decrease,
            lambda0=self.alpha0, maxiter=self.max_iter)

        self.coef_ = opt[0]
        self.alpha_ = opt[1]
        return self


class KernelRidge:

    def __init__(self, alpha0=[0.0, 0.0]):
        self.alpha0 = alpha0

    def fit(self, Xt, yt):
        self.Xt = Xt
        x0 = np.zeros(Xt.shape[0])

        # returns an approximate solution of the inner optimization
        K = pairwise_kernels(Xt, gamma=np.exp(self.alpha0[0]), metric='rbf')
        (out, success) = splinalg.cg(
            K + np.exp(self.alpha0[1]) * np.eye(x0.size), yt, x0=x0)
        if success is False:
            raise ValueError
        self.dual_coef_ = out

    def score(self, Xh, yh):
        # not really a score, more a loss
        lambdak = self.alpha0
        K_pred = pairwise_kernels(Xh, self.Xt, gamma=np.exp(lambdak[0]),
                                  metric='rbf')
        pred = K_pred.dot(self.dual_coef_)
        v = yh - pred
        return v.dot(v)