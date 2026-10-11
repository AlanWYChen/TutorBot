FROM node:24.12.0-bookworm-slim
ARG FIREBASE_TOOLS_VERSION=15.33.0
RUN npm install --global firebase-tools@${FIREBASE_TOOLS_VERSION}
WORKDIR /workspace
COPY infra/firebase/firebase.json ./firebase.json
RUN mkdir /data && chown -R node:node /data /workspace
USER node
EXPOSE 9099
CMD ["firebase", "emulators:start", "--only", "auth", "--project", "demo-tutorbot", "--import", "/data/export", "--export-on-exit", "/data/export"]
