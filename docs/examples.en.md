# DropLogic Examples

To help you get up to speed quickly, DropLogic comes with a dedicated `examples/` directory in the repository containing ready-to-run scripts. 

These scripts demonstrate how to initialize systems, instantiate multiple droplets, compute routes using our built-in SIPP planner, and execute asynchronous movements.

Below are the two main examples included by default:

## 1. Simulator Example (`simulator_example.py`)

This script demonstrates purely virtual routing without needing physical hardware attached. It initializes a 128x128 virtual matrix using our `Simulator` system, spawns 20 droplets (2x2 size each), and sets them into an infinite continuous-routing loop.

- Uses `Simulator` system (agnostic software).
- Frame execution delay is set to `0.5s` for fast visual feedback.
- When all 20 droplets reach their destination, it assigns new random coordinates and reroutes them automatically.

You can run it from the root directory via:
```bash
python3 examples/simulator_example.py
```

## 2. Hardware System Example (`DMLite_example.py`)

This script runs the exact same infinite routing loop as the simulator, but it binds directly to the physical hardware (`BOXMini` / `DMLite` AM-EWOD matrices). 

- Connects to hardware using the DropLogic physical abstraction stack.
- To accommodate fluid physics and hardware latency, the frame execution delay is set to a safer `1.0s`.
- Allows you to see real voltage actuations translating into droplet movement on the physical DMF chip.

Run it while connected to the AM-EWOD hardware:
```bash
python3 examples/DMLite_example.py
```
