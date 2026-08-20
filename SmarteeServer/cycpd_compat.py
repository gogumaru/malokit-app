"""
Compatibility wrapper for pycpd to match cycpd API
"""
import pycpd


def rigid_registration(**kwargs):
    """
    Wrapper to make pycpd.RigidRegistration behave like cycpd.rigid_registration
    """
    X = kwargs.get('X')
    Y = kwargs.get('Y')
    max_iterations = kwargs.get('max_iterations', 100)
    tolerance = kwargs.get('tolerance', 1e-3)
    w = kwargs.get('w', 0.0)
    
    # Create registration object
    reg = pycpd.RigidRegistration(X=X, Y=Y, max_iterations=max_iterations, tolerance=tolerance, w=w)
    
    # Store the original register method
    original_register = reg.register
    
    # Create wrapper that returns in the expected format
    def register_wrapper():
        TY, params = original_register()
        # pycpd returns (TY, (s, R, t))
        return TY, params
    
    # Replace the method
    reg.register = register_wrapper
    
    return reg


def affine_registration(**kwargs):
    """
    Wrapper to make pycpd.AffineRegistration behave like cycpd.affine_registration
    """
    X = kwargs.get('X')
    Y = kwargs.get('Y')
    max_iterations = kwargs.get('max_iterations', 100)
    tolerance = kwargs.get('tolerance', 1e-3)
    w = kwargs.get('w', 0.0)
    
    reg = pycpd.AffineRegistration(X=X, Y=Y, max_iterations=max_iterations, tolerance=tolerance, w=w)
    original_register = reg.register
    
    def register_wrapper():
        TY, params = original_register()
        return TY, params
    
    reg.register = register_wrapper
    
    return reg


def deformable_registration(**kwargs):
    """
    Wrapper to make pycpd.DeformableRegistration behave like cycpd.deformable_registration
    """
    X = kwargs.get('X')
    Y = kwargs.get('Y')
    max_iterations = kwargs.get('max_iterations', 100)
    tolerance = kwargs.get('tolerance', 1e-3)
    w = kwargs.get('w', 0.0)
    alpha = kwargs.get('alpha', 2.0)
    beta = kwargs.get('beta', 2.0)
    
    reg = pycpd.DeformableRegistration(
        X=X, Y=Y, max_iterations=max_iterations, tolerance=tolerance, w=w,
        alpha=alpha, beta=beta
    )
    original_register = reg.register
    
    def register_wrapper():
        TY, params = original_register()
        return TY, params
    
    reg.register = register_wrapper
    
    return reg
