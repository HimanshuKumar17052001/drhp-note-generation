build:
	sudo docker build -t drhp-be .
	sudo docker stop drhp-be01 || true
	sudo docker rm drhp-be01 || true
	sudo docker run -d -p 8001:8001 --name drhp-be01 drhp-be

