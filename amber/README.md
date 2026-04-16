# Amber instructions

## Provide env values
```bash
cp sample.env .env
```

And fill out the required values.

## Compile

```bash
./amber compile amber-scenario.json5 --docker-compose pi-bench.yml
```

## Run

```bash
export $(grep -v '^#' .env | xargs) && docker compose -f pi-bench.yml up
```
