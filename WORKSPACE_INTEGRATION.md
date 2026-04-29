# Workspace Integration

This document describes how `jupyter-positron-server` handles workspace directory integration with JupyterLab.

## Problem Solved

Previously, Positron launched from the server root directory regardless of the user's current JupyterLab workspace. Now Positron launches in the same directory context as the user's JupyterLab session.

## Implementation

### Working Directory Detection

The system uses a hierarchical approach to determine the workspace directory:

1. **`POSITRON_WORKSPACE`** - Explicit workspace override (highest priority)
2. **`JUPYTER_SERVER_ROOT`** - Jupyter server's root directory 
3. **Current working directory** - Fallback if neither environment variable is set

### Command Execution

Instead of passing the workspace as a command-line argument, the implementation:

1. Changes to the target workspace directory using `cd`
2. Sets the required `LD_LIBRARY_PATH` environment variable
3. Executes `positron-server` from that directory

This approach works because positron-server inherits the working directory from its execution context, similar to how running `cd ~/my-project && positron` opens Positron in that workspace.

## Configuration

### Environment Variables

- `POSITRON_WORKSPACE`: Set to explicitly control the workspace directory
- `JUPYTER_SERVER_ROOT`: Automatically set by Jupyter systems
- Standard JupyterLab/Hub environment variables are respected

### Example Usage

```bash
# Launch Positron in a specific workspace
export POSITRON_WORKSPACE="/home/user/my-python-project"

# Or let it inherit from Jupyter's root
# (JUPYTER_SERVER_ROOT is typically set automatically)
```

## Technical Details

The implementation modifies the `setup_positron_server()` function in `/jupyter-positron-server/__init__.py`:

1. **Directory Resolution**: Expands `~` and resolves to absolute paths
2. **Directory Creation**: Creates the workspace directory if it doesn't exist
3. **Shell Command**: Uses `/bin/bash -c` to combine directory change and process execution
4. **Security**: Uses `shlex.quote()` and `shlex.join()` to safely handle paths with spaces and special characters

## Benefits

- Positron opens in the user's current JupyterLab workspace
- Seamless workflow transition between JupyterLab and Positron
- Respects existing Jupyter environment configuration
- Configurable via environment variables for different deployment scenarios